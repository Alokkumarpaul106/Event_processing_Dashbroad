"""Render HTML evidence reports from captured REST and local MQTT JSON."""

import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def page(title, subtitle, panels):
    cards = "\n".join(
        f"<section><h2>{html.escape(label)}</h2><pre>{html.escape(json.dumps(data, indent=2, ensure_ascii=False))}</pre></section>"
        for label, data in panels
    )
    return f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
*{{box-sizing:border-box}} body{{margin:0;padding:32px;background:#f4f6f8;color:#172033;font:15px/1.5 system-ui,Segoe UI,sans-serif}}
main{{max-width:1100px;margin:auto}} header,section{{background:white;border:1px solid #d9dee8;border-radius:12px;padding:20px;margin-bottom:16px}}
h1{{margin:0 0 6px}} h2{{font-size:17px;margin:0 0 12px}} p{{margin:0;color:#475467}}
pre{{margin:0;padding:16px;border-radius:8px;overflow:auto;background:#0f172a;color:#e2e8f0;font:13px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}}
.note{{border-left:4px solid #b54708;padding-left:12px;margin-top:12px;color:#7a2e0e}}
</style><main><header><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></header>{cards}</main></html>"""


rest = json.loads((ROOT / "rest-api-results.json").read_text(encoding="utf-8-sig"))
rest_labels = {
    "accepted_count_500": "POST /api/events — COUNT 500 accepted",
    "duplicate_delivery": "POST /api/events — identical delivery classified DUPLICATE",
    "rejected_count_501": "POST /api/events — COUNT 501 rejected",
    "accepted_count_for_ack": "POST /api/events — acknowledgement example accepted",
    "acknowledgement": "POST /api/ack",
    "summary": "GET /api/state?view=summary&source_id=LINE-ASSESS-01",
    "pending": "GET /api/state?view=pending&source_id=LINE-ASSESS-01",
    "exceptions": "GET /api/state?view=exceptions&source_id=LINE-ASSESS-01",
}
(ROOT / "rest-api-results.html").write_text(
    page(
        "REST API verification",
        "Captured JSON responses from HTTP requests to the temporary local Django server.",
        [(label, rest[key]) for key, label in rest_labels.items()],
    ),
    encoding="utf-8",
)

mqtt = json.loads((ROOT / "mqtt-challenge-results.json").read_text(encoding="utf-8-sig"))
(ROOT / "mqtt-challenge-results.html").write_text(
    page(
        "MQTT challenge handler verification",
        "Local database-backed handler replay check. This report does not claim a live broker connection.",
        [("Transport and replay assertion", {key: value for key, value in mqtt.items() if key not in {"first_response", "replayed_response"}}), ("First response", mqtt["first_response"]), ("Stored response returned on replay", mqtt["replayed_response"])],
    ),
    encoding="utf-8",
)
