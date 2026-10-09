"""Production event rules shared by the HTTP API and the MQTT adapter."""

import re
from datetime import datetime, timezone

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.utils import timezone as django_timezone

from .models import MqttChallenge, MqttRuntimeState, ProductionEvent, ProductionSource, SubmissionAttempt

ITEM_STATUSES = {name: name for name in ("ACCEPTED", "DUPLICATE", "CONFLICT", "PENDING_REFERENCE", "REJECTED")}
EVENT_TYPES = ("COUNT", "VOID")
MAX_COUNT_QUANTITY = 500
EVENT_TIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:?\d{2})$"
)


def safe_id(value):
    return value.strip()[:200] if isinstance(value, str) and value.strip() else None


def parse_event_time(value):
    if not isinstance(value, str) or not EVENT_TIME_RE.fullmatch(value.strip()):
        raise ValueError("event_time must be an ISO 8601 timestamp with timezone, e.g. 2026-10-09T10:30:00Z")
    text = value.strip().replace("Z", "+00:00")
    # Python datetimes store microseconds; extra ISO fractional digits do not
    # change the instant precision supported by the database.
    text = re.sub(r"\.(\d{6})\d+(?=[+-])", r".\1", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("event_time is not a valid date") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("event_time must include a timezone")
    return parsed.astimezone(timezone.utc)


def isoformat(value):
    if value is None:
        return None
    if django_timezone.is_naive(value):
        value = django_timezone.make_aware(value, timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_event(raw):
    if not isinstance(raw, dict):
        return None, ["Event must be a JSON object"]
    errors = []
    source_id = raw.get("source_id")
    event_id = raw.get("event_id")
    if not isinstance(source_id, str) or not source_id.strip():
        errors.append("source_id is required and must be a non-empty string")
    if not isinstance(event_id, str) or not event_id.strip():
        errors.append("event_id is required and must be a non-empty string")
    event_type = raw.get("type")
    if event_type not in EVENT_TYPES:
        errors.append("type must be exactly COUNT or VOID")

    quantity = None
    target = None
    if event_type == "COUNT":
        raw_quantity = raw.get("quantity")
        if type(raw_quantity) is not int or not 1 <= raw_quantity <= MAX_COUNT_QUANTITY:
            errors.append(f"COUNT quantity must be an integer from 1 to {MAX_COUNT_QUANTITY}, inclusive")
        else:
            quantity = raw_quantity
        if raw.get("target_event_id") is not None:
            errors.append("COUNT target_event_id must be null or omitted")
    elif event_type == "VOID":
        if raw.get("quantity") is not None:
            errors.append("VOID quantity must be null or omitted")
        target_value = raw.get("target_event_id")
        if not isinstance(target_value, str) or not target_value.strip():
            errors.append("VOID target_event_id is required (ID of the COUNT being reversed)")
        else:
            target = target_value.strip()
        if target and isinstance(event_id, str) and event_id.strip() and target == event_id.strip():
            errors.append("VOID cannot target itself")

    event_time = None
    try:
        event_time = parse_event_time(raw.get("event_time"))
    except ValueError as exc:
        errors.append(str(exc))

    if errors:
        return None, errors
    normalized = {
        "source_id": source_id.strip(),
        "event_id": event_id.strip(),
        "type": event_type,
        "quantity": quantity,
        "target_event_id": target,
        "event_time": isoformat(event_time),
    }
    return normalized, []


def _same_event(left, right):
    if not left:
        return False
    try:
        left_time = parse_event_time(left["event_time"])
        right_time = parse_event_time(right["event_time"])
    except (KeyError, TypeError, ValueError):
        return False
    return all(
        [
            left.get("source_id") == right.get("source_id"),
            left.get("event_id") == right.get("event_id"),
            left.get("type") == right.get("type"),
            left.get("quantity") == right.get("quantity"),
            left.get("target_event_id") == right.get("target_event_id"),
            left_time == right_time,
        ]
    )


def _lock_key(key):
    # SQLite serializes writers itself. PostgreSQL advisory transaction locks
    # also serialize an arriving COUNT and any VOID that references it.
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [key])


def _record_attempt(raw, normalized, status, message, ctx):
    source_id = normalized.get("source_id") if normalized else safe_id(raw.get("source_id") if isinstance(raw, dict) else None)
    event_id = normalized.get("event_id") if normalized else safe_id(raw.get("event_id") if isinstance(raw, dict) else None)
    SubmissionAttempt.objects.create(
        channel=ctx.get("channel") or "REST",
        challenge_id=ctx.get("challenge_id"),
        payload=raw,
        source_id=source_id,
        event_id=event_id,
        classification=status,
        error=None if status == "ACCEPTED" else message,
    )


def _result(raw, status, message, normalized=None):
    raw_id = raw.get("event_id") if isinstance(raw, dict) else None
    item = {"event_id": normalized.get("event_id") if normalized else safe_id(raw_id), "status": status, "message": message}
    if status == "REJECTED":
        item["reason"] = message
    return item


def _finish(raw, normalized, ctx, status, message):
    _record_attempt(raw, normalized, status, message, ctx)
    return _result(raw, status, message, normalized)


def _classify_existing(raw, event, existing, ctx):
    if _same_event(existing.normalized, event):
        return _finish(raw, event, ctx, "DUPLICATE", "Identical event already received; not processed again")
    return _finish(raw, event, ctx, "CONFLICT", "Event ID already exists with different data; original event preserved")


def _insert_event(event, status, auto_ack=False):
    try:
        with transaction.atomic():
            return ProductionEvent.objects.create(
                source_id=event["source_id"],
                event_id=event["event_id"],
                type=event["type"],
                quantity=event["quantity"],
                target_event_id=event["target_event_id"],
                event_time=parse_event_time(event["event_time"]),
                status=status,
                normalized=event,
                resolved_at=django_timezone.now() if status == "PROCESSED" and event["type"] == "VOID" else None,
                acknowledged_at=django_timezone.now() if auto_ack else None,
            )
    except IntegrityError:
        return None


def process_event(raw, ctx=None, notes=None):
    ctx = ctx or {}
    notes = notes if notes is not None else []
    event, errors = validate_event(raw)
    if errors:
        return _finish(raw, None, ctx, "REJECTED", "; ".join(errors))

    source_id = event["source_id"]
    event_id = event["event_id"]
    lock_target = event_id if event["type"] == "COUNT" else event["target_event_id"]
    _lock_key(f"{source_id}\x1f{lock_target}")
    ProductionSource.objects.get_or_create(source_id=source_id, defaults={"display_name": source_id})

    existing = ProductionEvent.objects.filter(source_id=source_id, event_id=event_id).first()
    if existing:
        return _classify_existing(raw, event, existing, ctx)

    if event["type"] == "COUNT":
        row = _insert_event(event, "PROCESSED")
        if row is None:
            existing = ProductionEvent.objects.filter(source_id=source_id, event_id=event_id).first()
            if existing:
                return _classify_existing(raw, event, existing, ctx)
            raise RuntimeError("Could not save production event")
        notes.append(("EVENT_ACCEPTED", {"source_id": source_id, "event_id": event_id, "type": "COUNT"}))
        pending = ProductionEvent.objects.filter(
            source_id=source_id,
            type="VOID",
            target_event_id=event_id,
            status="PENDING_REFERENCE",
        ).first()
        if pending:
            now = django_timezone.now()
            pending.status = "PROCESSED"
            pending.resolved_at = now
            pending.acknowledged_at = now
            pending.save(update_fields=["status", "resolved_at", "acknowledged_at"])
            notes.append(("VOID_RESOLVED", {"source_id": source_id, "event_id": pending.event_id, "target_event_id": event_id}))
        message = f"Event processed; pending VOID {pending.event_id} resolved" if pending else "Event processed"
        return _finish(raw, event, ctx, "ACCEPTED", message)

    # VOID: the first valid correction for a COUNT wins.
    previous_void = ProductionEvent.objects.filter(
        source_id=source_id, type="VOID", target_event_id=event["target_event_id"]
    ).first()
    if previous_void:
        return _finish(
            raw,
            event,
            ctx,
            "REJECTED",
            f"COUNT {event['target_event_id']} already has VOID {previous_void.event_id} ({previous_void.status}); the first valid VOID wins",
        )

    target = ProductionEvent.objects.filter(source_id=source_id, event_id=event["target_event_id"]).first()
    if target and target.type != "COUNT":
        return _finish(raw, event, ctx, "REJECTED", f"target_event_id {event['target_event_id']} is not a COUNT event")
    if target:
        row = _insert_event(event, "PROCESSED", auto_ack=True)
        if row is None:
            existing = ProductionEvent.objects.filter(source_id=source_id, event_id=event_id).first()
            if existing:
                return _classify_existing(raw, event, existing, ctx)
            previous_void = ProductionEvent.objects.filter(
                source_id=source_id, type="VOID", target_event_id=event["target_event_id"]
            ).first()
            if previous_void:
                return _finish(raw, event, ctx, "REJECTED", f"COUNT {event['target_event_id']} already has VOID {previous_void.event_id} ({previous_void.status}); the first valid VOID wins")
            raise RuntimeError("Could not save VOID event")
        notes.append(("EVENT_ACCEPTED", {"source_id": source_id, "event_id": event_id, "type": "VOID"}))
        return _finish(raw, event, ctx, "ACCEPTED", "Event processed")

    other_source = ProductionEvent.objects.filter(event_id=event["target_event_id"], type="COUNT").exclude(source_id=source_id).values_list("source_id", flat=True).first()
    if other_source:
        return _finish(
            raw,
            event,
            ctx,
            "REJECTED",
            f"COUNT {event['target_event_id']} belongs to {other_source}; COUNT and VOID must have the same source_id",
        )
    row = _insert_event(event, "PENDING_REFERENCE")
    if row is None:
        existing = ProductionEvent.objects.filter(source_id=source_id, event_id=event_id).first()
        if existing:
            return _classify_existing(raw, event, existing, ctx)
        previous_void = ProductionEvent.objects.filter(
            source_id=source_id, type="VOID", target_event_id=event["target_event_id"]
        ).first()
        if previous_void:
            return _finish(raw, event, ctx, "REJECTED", f"COUNT {event['target_event_id']} already has VOID {previous_void.event_id} ({previous_void.status}); the first valid VOID wins")
        raise RuntimeError("Could not save pending VOID")
    return _finish(raw, event, ctx, "PENDING_REFERENCE", f"VOID stored; waiting for COUNT {event['target_event_id']}")


def process_batch(items, ctx=None, notes=None):
    ctx = ctx or {}
    notes = notes if notes is not None else []
    return [process_event(item, ctx, notes) for item in items]


def submit_events(items, ctx=None):
    for attempt in range(4):
        notes = []
        try:
            with transaction.atomic():
                results = process_batch(items, ctx or {"channel": "REST"}, notes)
            emit_domain_events(notes)
            return results
        except DatabaseError as exc:
            cause = exc.__cause__
            sqlstate = getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)
            if sqlstate not in {"40P01", "40001"} or attempt == 3:
                raise
    raise RuntimeError("Could not submit event batch")


def emit_domain_events(notes):
    """Send lightweight Django signals only after the transaction commits."""
    from . import domain_events

    for name, payload in notes:
        signal = getattr(domain_events, name.lower(), None)
        if signal:
            transaction.on_commit(lambda signal=signal, payload=payload: signal.send_robust(sender=None, payload=payload))


def acknowledge_events(event_ids):
    notes = []
    output = []
    with transaction.atomic():
        for raw_id in event_ids:
            if not isinstance(raw_id, str) or not raw_id.strip():
                output.append({"event_id": raw_id, "status": "NOT_FOUND", "message": "Invalid event id"})
                continue
            event_id = raw_id.strip()
            rows = list(
                ProductionEvent.objects.select_for_update()
                .filter(event_id=event_id)
                .order_by("id")
            )
            if not rows:
                rejected = SubmissionAttempt.objects.filter(
                    event_id=event_id, classification__in=["REJECTED", "CONFLICT"]
                ).exists()
                if rejected:
                    output.append({"event_id": event_id, "status": "NOT_READY", "message": "Event was rejected; nothing to acknowledge"})
                else:
                    output.append({"event_id": event_id, "status": "NOT_FOUND", "message": "No event with this ID"})
                continue
            ready = [row for row in rows if row.status == "PROCESSED" and row.acknowledged_at is None]
            if ready:
                now = django_timezone.now()
                ProductionEvent.objects.filter(pk__in=[row.pk for row in ready], acknowledged_at__isnull=True).update(acknowledged_at=now)
                notes.append(("EVENT_ACKNOWLEDGED", {"event_id": event_id}))
                output.append({"event_id": event_id, "status": "ACKED", "message": "Acknowledged"})
            elif any(row.status == "PROCESSED" and row.acknowledged_at for row in rows):
                output.append({"event_id": event_id, "status": "ALREADY_ACKED", "message": "Already acknowledged"})
            else:
                output.append({"event_id": event_id, "status": "NOT_READY", "message": "Event is unresolved (waiting for its COUNT)"})
    emit_domain_events(notes)
    return output


def _filtered_events(source_id=None):
    events = ProductionEvent.objects.all()
    return events.filter(source_id=source_id) if source_id else events


def get_summary(source_id=None):
    events = _filtered_events(source_id)
    completed_void = ProductionEvent.objects.filter(
        type="VOID", status="PROCESSED", source_id=OuterRef("source_id"), target_event_id=OuterRef("event_id")
    )
    net = (
        events.filter(type="COUNT")
        .annotate(has_void=Exists(completed_void))
        .filter(has_void=False)
        .aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    attempts = SubmissionAttempt.objects.all()
    if source_id:
        attempts = attempts.filter(source_id=source_id)
    return {
        "net_total": int(net),
        "processed_events": events.filter(status="PROCESSED").count(),
        "pending_ack": events.filter(status="PROCESSED", acknowledged_at__isnull=True).count(),
        "unresolved": events.filter(status="PENDING_REFERENCE").count(),
        "duplicates": attempts.filter(classification="DUPLICATE").count(),
        "conflicts": attempts.filter(classification="CONFLICT").count(),
        "rejected_submissions": attempts.filter(classification="REJECTED").count(),
    }


def get_pending(source_id=None):
    rows = _filtered_events(source_id).filter(status="PROCESSED", acknowledged_at__isnull=True)
    return [
        {
            "source_id": row.source_id,
            "event_id": row.event_id,
            "type": row.type,
            "quantity": row.quantity,
            "target_event_id": row.target_event_id,
            "event_time": isoformat(row.event_time),
            "received_at": isoformat(row.received_at),
            "status": row.status,
        }
        for row in rows
    ]


def get_sources():
    registered = ProductionSource.objects.values_list("source_id", flat=True)
    submitted = SubmissionAttempt.objects.exclude(source_id__isnull=True).values_list("source_id", flat=True)
    return sorted(set(registered).union(submitted))


def get_exceptions(source_id=None):
    unresolved = _filtered_events(source_id).filter(status="PENDING_REFERENCE").values(
        "source_id", "event_id", "type", "quantity", "target_event_id", "event_time", "received_at", "status"
    )
    rows = [
        {
            "kind": "UNRESOLVED",
            "source_id": row["source_id"],
            "event_id": row["event_id"],
            "type": row["type"],
            "quantity": row["quantity"],
            "target_event_id": row["target_event_id"],
            "event_time": isoformat(row["event_time"]),
            "status": row["status"],
            "reason": f"Waiting for COUNT {row['target_event_id']}",
            "received_at": isoformat(row["received_at"]),
        }
        for row in unresolved
    ]
    attempts = SubmissionAttempt.objects.filter(classification__in=["REJECTED", "CONFLICT"])
    if source_id:
        attempts = attempts.filter(source_id=source_id)
    for attempt in attempts[:1000]:
        payload = attempt.payload if isinstance(attempt.payload, dict) else {}
        quantity = payload.get("quantity")
        if type(quantity) is not int:
            quantity = None
        rows.append(
            {
                "kind": "ATTEMPT",
                "source_id": attempt.source_id,
                "event_id": attempt.event_id,
                "type": payload.get("type"),
                "quantity": quantity,
                "target_event_id": payload.get("target_event_id"),
                "event_time": None,
                "status": attempt.classification,
                "reason": attempt.error,
                "received_at": isoformat(attempt.received_at),
            }
        )
    rows.sort(key=lambda item: item["received_at"] or "", reverse=True)
    return rows[:500]


def get_mqtt_dashboard():
    from django.conf import settings

    from .mqtt_status import mqtt_status

    latest = MqttChallenge.objects.first()
    aggregates = MqttChallenge.objects.aggregate(
        total=Count("challenge_id"),
        completed=Count("challenge_id", filter=Q(status="COMPLETED")),
        failed=Count("challenge_id", filter=Q(status="FAILED")),
    )
    runtime = MqttRuntimeState.objects.filter(pk=1).first()
    latest_failure = MqttChallenge.objects.filter(status="FAILED").first()
    last_error = (runtime.last_error if runtime else None) or mqtt_status.get("last_error")
    if not last_error and latest and latest.error_code:
        last_error = {"code": latest.error_code, "message": latest.error_message, "at": isoformat(latest.received_at)}
    connect_error = runtime.last_connect_error if runtime else mqtt_status.get("last_connect_error")
    runtime_connected = bool(
        runtime
        and runtime.connected
        and runtime.last_heartbeat_at
        and (django_timezone.now() - runtime.last_heartbeat_at).total_seconds() < 90
    )
    if not last_error and connect_error:
        last_error = {"code": "CONNECTION", "message": connect_error, "at": None}
    return {
        "enabled": settings.MQTT_ENABLED,
        "connected": runtime_connected if runtime else mqtt_status.get("connected", False),
        "candidate_id": (runtime.candidate_id if runtime and runtime.candidate_id else None) or mqtt_status.get("candidate_id") or settings.CANDIDATE_ID,
        "broker": (runtime.broker if runtime and runtime.broker else None) or mqtt_status.get("broker") or settings.MQTT_URL,
        "last_heartbeat_at": isoformat(runtime.last_heartbeat_at) if runtime and runtime.last_heartbeat_at else mqtt_status.get("last_heartbeat_at"),
        "last_challenge_id": latest.challenge_id if latest else None,
        "last_challenge_at": isoformat(latest.received_at) if latest else None,
        "last_response_status": latest.status if latest else None,
        "challenge_counts": {
            "total": aggregates["total"],
            "completed": aggregates["completed"],
            "failed": aggregates["failed"],
        },
        "last_error": last_error or (
            {"code": latest_failure.error_code, "message": latest_failure.error_message, "at": isoformat(latest_failure.received_at)}
            if latest_failure
            else None
        ),
    }
