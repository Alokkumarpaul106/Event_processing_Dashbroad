import json
import logging

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from . import services

logger = logging.getLogger(__name__)


@require_GET
def dashboard(request):
    return render(request, "dashboard/index.html")


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, JsonResponse({"error": "Invalid JSON body"}, status=400)


def _server_error():
    logger.exception("Dashboard API request failed")
    return JsonResponse({"error": "Internal server error"}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def events_api(request):
    body, error = _json_body(request)
    if error:
        return error
    if body is None or not isinstance(body, (dict, list)):
        return JsonResponse({"error": "Request body must be a JSON event object or an array of events"}, status=400)
    items = body if isinstance(body, list) else [body]
    try:
        return JsonResponse({"results": services.submit_events(items, {"channel": "REST"})})
    except Exception:
        return _server_error()


@require_GET
def state_api(request):
    view = request.GET.get("view")
    if view not in {"summary", "pending", "exceptions"}:
        return JsonResponse({"error": "view must be one of summary, pending, exceptions"}, status=400)
    source_id = request.GET.get("source_id", "").strip() or None
    try:
        if view == "summary":
            payload = {
                "view": view,
                "source_id": source_id,
                **services.get_summary(source_id),
                "sources": services.get_sources(),
                "mqtt": services.get_mqtt_dashboard(),
            }
        else:
            items = services.get_pending(source_id) if view == "pending" else services.get_exceptions(source_id)
            payload = {"view": view, "source_id": source_id, "count": len(items), "items": items}
        return JsonResponse(payload)
    except Exception:
        return _server_error()


@csrf_exempt
@require_http_methods(["POST"])
def ack_api(request):
    body, error = _json_body(request)
    if error:
        return error
    ids = body.get("event_ids") if isinstance(body, dict) else None
    if not isinstance(ids, list):
        return JsonResponse({"error": "event_ids must be an array of event ID strings"}, status=400)
    try:
        return JsonResponse({"results": services.acknowledge_events(ids)})
    except Exception:
        return _server_error()
