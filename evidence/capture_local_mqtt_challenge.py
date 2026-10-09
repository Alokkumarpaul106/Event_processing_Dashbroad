"""Run the MQTT challenge handler against the configured Django database."""

import json
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django

django.setup()

from django.utils import timezone

from dashboard.mqtt import handle_challenge_message
from dashboard.services import isoformat


candidate_id = "CAND-LOCAL-DEMO"
now = timezone.now()
challenge = {
    "protocol_version": "1.0",
    "candidate_id": candidate_id,
    "challenge_id": "CH-ASSESS-LOCAL-001",
    "command": "PROCESS_EVENTS",
    "expires_at": isoformat(now + timedelta(minutes=5)),
    "events": [
        {
            "source_id": "LINE-ASSESS-01",
            "event_id": "EV-MQTT-LOCAL-001",
            "type": "COUNT",
            "quantity": 3,
            "target_event_id": None,
            "event_time": isoformat(now),
        }
    ],
}
raw = json.dumps(challenge)
first = handle_challenge_message(raw, candidate_id=candidate_id, now=now)["response"]
replay = handle_challenge_message(raw, candidate_id=candidate_id, now=now)["response"]

print(
    json.dumps(
        {
            "transport": "local challenge handler; no broker connection",
            "replay_matches_stored_response": first == replay,
            "first_response": first,
            "replayed_response": replay,
        },
        indent=2,
    )
)
