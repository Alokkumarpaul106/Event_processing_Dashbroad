"""MQTT challenge protocol and optional outbound worker."""

import hashlib
import json
import logging
import secrets
import time
from datetime import datetime
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import services
from .models import MqttChallenge, MqttRuntimeState
from .mqtt_status import mqtt_status

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "1.0"
COMMAND = "PROCESS_EVENTS"
QOS = 1
HEARTBEAT_SECONDS = 30
ERRORS = {
    "VALIDATION_ERROR",
    "CANDIDATE_MISMATCH",
    "UNSUPPORTED_PROTOCOL",
    "CHALLENGE_EXPIRED",
    "CHALLENGE_CONFLICT",
    "INTERNAL_ERROR",
}


def topics(candidate_id):
    root = f"fse-01/{candidate_id}"
    return {"challenge": f"{root}/challenge", "response": f"{root}/response", "status": f"{root}/status"}


def _digest(value):
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _persist_runtime():
    try:
        from django.db import close_old_connections

        close_old_connections()
        last_heartbeat = mqtt_status.get("last_heartbeat_at")
        MqttRuntimeState.objects.update_or_create(
            pk=1,
            defaults={
                "candidate_id": mqtt_status.get("candidate_id") or settings.CANDIDATE_ID,
                "broker": mqtt_status.get("broker") or settings.MQTT_URL,
                "connected": mqtt_status.get("connected", False),
                "last_heartbeat_at": datetime.fromisoformat(last_heartbeat.replace("Z", "+00:00")) if last_heartbeat else None,
                "last_connect_error": mqtt_status.get("last_connect_error"),
                "last_error": mqtt_status.get("last_error"),
            },
        )
    except Exception:
        logger.exception("Could not save MQTT runtime status")


def _failed(candidate_id, challenge_id, code, message, now=None):
    return {
        "protocol_version": PROTOCOL_VERSION,
        "candidate_id": candidate_id,
        "challenge_id": challenge_id,
        "status": "FAILED",
        "error_code": code,
        "message": message,
        "processed_at": services.isoformat(now or timezone.now()),
    }


def _header_error(challenge, candidate_id):
    if not isinstance(challenge, dict):
        return "VALIDATION_ERROR", "Challenge must be a JSON object"
    if challenge.get("protocol_version") != PROTOCOL_VERSION:
        return "UNSUPPORTED_PROTOCOL", f"Unsupported protocol_version {json.dumps(challenge.get('protocol_version'))}; expected {PROTOCOL_VERSION}"
    if challenge.get("candidate_id") != candidate_id:
        return "CANDIDATE_MISMATCH", f"candidate_id {json.dumps(challenge.get('candidate_id'))} does not match this client ({candidate_id})"
    if not isinstance(challenge.get("challenge_id"), str) or not challenge["challenge_id"].strip():
        return "VALIDATION_ERROR", "challenge_id is required"
    if challenge.get("command") != COMMAND:
        return "VALIDATION_ERROR", f"command must be {COMMAND}"
    return None


def _body_error(challenge, now):
    expires_at = challenge.get("expires_at")
    if not isinstance(expires_at, str):
        return "VALIDATION_ERROR", "expires_at must be an ISO 8601 timestamp"
    try:
        expiry = services.parse_event_time(expires_at)
    except ValueError:
        return "VALIDATION_ERROR", "expires_at must be an ISO 8601 timestamp"
    if now >= expiry:
        return "CHALLENGE_EXPIRED", f"Challenge expired at {expires_at}"
    if not isinstance(challenge.get("events"), list):
        return "VALIDATION_ERROR", "events must be an array"
    return None


def _completed(candidate_id, challenge_id, results, state, now):
    return {
        "protocol_version": PROTOCOL_VERSION,
        "candidate_id": candidate_id,
        "challenge_id": challenge_id,
        "status": "COMPLETED",
        "processed_at": services.isoformat(now),
        "results": [
            {"event_id": result.get("event_id"), "status": result["status"], "message": result["message"]}
            for result in results
        ],
        "state": {
            key: state[key]
            for key in ("net_total", "processed_events", "pending_ack", "unresolved", "duplicates", "conflicts")
        },
    }


def handle_challenge_message(raw_text, candidate_id=None, now=None):
    """Process a challenge once; an identical replay returns its stored answer."""
    candidate_id = candidate_id or settings.CANDIDATE_ID
    now = now or timezone.now()
    try:
        challenge = json.loads(raw_text)
    except (TypeError, json.JSONDecodeError):
        code, message = "VALIDATION_ERROR", "Challenge is not valid JSON"
        mqtt_status["last_error"] = {"code": code, "message": message, "at": services.isoformat(now)}
        _persist_runtime()
        return {"response": _failed(candidate_id, None, code, message, now), "challenge_id": None}

    header_error = _header_error(challenge, candidate_id)
    challenge_id = challenge.get("challenge_id", "").strip() if isinstance(challenge, dict) and isinstance(challenge.get("challenge_id"), str) else None
    challenge_id = challenge_id or None
    if header_error and not challenge_id:
        code, message = header_error
        mqtt_status["last_error"] = {"code": code, "message": message, "at": services.isoformat(now)}
        _persist_runtime()
        return {"response": _failed(candidate_id, None, code, message, now), "challenge_id": None}

    digest = _digest(challenge)
    notes = []
    try:
        with transaction.atomic():
            if connection_is_postgresql():
                from django.db import connection

                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"challenge\x1f{challenge_id}"])
            previous = MqttChallenge.objects.select_for_update().filter(challenge_id=challenge_id).first()
            if previous:
                if previous.request_digest == digest:
                    return {"response": previous.response, "challenge_id": challenge_id}
                code, message = "CHALLENGE_CONFLICT", f"challenge_id {challenge_id} was already used with a different body"
                mqtt_status["last_error"] = {"code": code, "message": message, "at": services.isoformat(now)}
                _persist_runtime()
                return {"response": _failed(candidate_id, challenge_id, code, message, now), "challenge_id": challenge_id}

            error = header_error or _body_error(challenge, now)
            if error:
                code, message = error
                response = _failed(candidate_id, challenge_id, code, message, now)
                mqtt_status["last_error"] = {"code": code, "message": message, "at": services.isoformat(now)}
            else:
                results = services.process_batch(
                    challenge["events"], {"channel": "MQTT", "challenge_id": challenge_id}, notes
                )
                response = _completed(candidate_id, challenge_id, results, services.get_summary(), now)
            MqttChallenge.objects.create(
                challenge_id=challenge_id,
                request_digest=digest,
                request_body=challenge,
                status=response["status"],
                error_code=response.get("error_code"),
                error_message=response.get("message"),
                response=response,
                responded_at=timezone.now(),
            )
        services.emit_domain_events(notes)
        _persist_runtime()
        return {"response": response, "challenge_id": challenge_id}
    except Exception:
        logger.exception("MQTT challenge processing failed")
        code, message = "INTERNAL_ERROR", "Internal error while processing challenge"
        mqtt_status["last_error"] = {"code": code, "message": message, "at": services.isoformat(now)}
        _persist_runtime()
        return {"response": _failed(candidate_id, challenge_id, code, message, now), "challenge_id": challenge_id}


def connection_is_postgresql():
    from django.db import connection

    return connection.vendor == "postgresql"


def mark_published(challenge_id):
    if challenge_id:
        MqttChallenge.objects.filter(challenge_id=challenge_id, published_at__isnull=True).update(published_at=timezone.now())


def run_worker():
    """Connect to the configured broker and serve challenges until interrupted."""
    import paho.mqtt.client as mqtt
    from django.db import close_old_connections

    if not settings.MQTT_ENABLED:
        raise RuntimeError("MQTT is disabled; set MQTT_ENABLED=true in .env to start the worker")

    broker = urlparse(settings.MQTT_URL)
    if broker.scheme not in {"mqtt", "mqtts", "tcp", "ssl"} or not broker.hostname:
        raise ValueError("MQTT_URL must be an mqtt:// or mqtts:// URL")
    candidate_id = settings.CANDIDATE_ID
    topic = topics(candidate_id)
    port = broker.port or (8883 if broker.scheme in {"mqtts", "ssl"} else 1883)
    status_options = {"qos": QOS, "retain": False}
    pending_publish = {}

    def status_payload(value):
        return json.dumps({"candidate_id": candidate_id, "status": value, "at": services.isoformat(timezone.now())})

    def publish_status(client, value):
        if value != "OFFLINE":
            mqtt_status["last_heartbeat_at"] = services.isoformat(timezone.now())
        client.publish(topic["status"], status_payload(value), **status_options)
        _persist_runtime()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fse01-{candidate_id}-{secrets.token_hex(3)}", protocol=mqtt.MQTTv311)
    if broker.username:
        client.username_pw_set(unquote(broker.username), unquote(broker.password or ""))
    if broker.scheme in {"mqtts", "ssl"}:
        client.tls_set()
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.will_set(topic["status"], status_payload("OFFLINE"), qos=QOS, retain=False)
    mqtt_status.update(
        {"connected": False, "candidate_id": candidate_id, "broker": settings.MQTT_URL, "last_connect_error": None}
    )
    _persist_runtime()

    def on_connect(mqtt_client, _userdata, _flags, reason_code, _properties):
        if reason_code.is_failure:
            mqtt_status["last_connect_error"] = str(reason_code)
            _persist_runtime()
            return
        mqtt_status["last_connect_error"] = None
        result, _mid = mqtt_client.subscribe(topic["challenge"], qos=QOS)
        if result != mqtt.MQTT_ERR_SUCCESS:
            mqtt_status["last_connect_error"] = f"subscribe failed: {mqtt.error_string(result)}"
            _persist_runtime()
            return
        mqtt_status["connected"] = True
        publish_status(mqtt_client, "ONLINE")
        _persist_runtime()

    def on_disconnect(_client, _userdata, _disconnect_flags, reason_code, _properties):
        mqtt_status["connected"] = False
        if reason_code.is_failure:
            mqtt_status["last_connect_error"] = str(reason_code)
        _persist_runtime()

    def on_message(mqtt_client, _userdata, message):
        if message.topic != topic["challenge"]:
            return
        close_old_connections()
        try:
            result = handle_challenge_message(message.payload.decode("utf-8", errors="replace"), candidate_id)
            info = mqtt_client.publish(topic["response"], json.dumps(result["response"]), **status_options)
            if result["challenge_id"] and info.rc == mqtt.MQTT_ERR_SUCCESS:
                pending_publish[info.mid] = result["challenge_id"]
        finally:
            close_old_connections()

    def on_publish(_client, _userdata, mid, _reason_code, _properties):
        challenge_id = pending_publish.pop(mid, None)
        if challenge_id:
            close_old_connections()
            try:
                mark_published(challenge_id)
            finally:
                close_old_connections()

    def on_log(_client, _userdata, level, buf):
        if level >= mqtt.MQTT_LOG_ERR:
            mqtt_status["last_connect_error"] = buf
            _persist_runtime()
            logger.error("MQTT: %s", buf)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.on_publish = on_publish
    client.on_log = on_log

    logger.info("Connecting MQTT worker to %s", settings.MQTT_URL)
    client.connect(broker.hostname, port, keepalive=30)
    client.loop_start()
    try:
        while True:
            time.sleep(HEARTBEAT_SECONDS)
            if mqtt_status["connected"]:
                publish_status(client, "HEARTBEAT")
    except KeyboardInterrupt:
        logger.info("Stopping MQTT worker")
    finally:
        mqtt_status["connected"] = False
        _persist_runtime()
        try:
            client.publish(topic["status"], status_payload("OFFLINE"), **status_options)
            client.disconnect()
        finally:
            client.loop_stop()
