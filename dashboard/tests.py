import json
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from . import mqtt
from .models import MqttChallenge, ProductionEvent, SubmissionAttempt


class ProductionFlowTests(TestCase):
    def setUp(self):
        self.event_time = "2026-10-09T10:30:00Z"

    def count_event(self, event_id="COUNT-1", quantity=7, source_id="LINE-01"):
        return {
            "source_id": source_id,
            "event_id": event_id,
            "type": "COUNT",
            "quantity": quantity,
            "target_event_id": None,
            "event_time": self.event_time,
        }

    def post_events(self, events):
        response = self.client.post(
            "/api/events",
            data=json.dumps(events),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def summary(self, source_id="LINE-01"):
        response = self.client.get(
            "/api/state",
            {"view": "summary", "source_id": source_id},
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_count_boundary_500_is_accepted_and_501_is_audited_rejection(self):
        accepted, rejected = self.post_events(
            [
                self.count_event("COUNT-500", quantity=500),
                self.count_event("COUNT-501", quantity=501),
            ]
        )

        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertIn("1 to 500", rejected["reason"])
        state = self.summary()
        self.assertEqual(state["net_total"], 500)
        self.assertEqual(state["rejected_submissions"], 1)
        self.assertEqual(ProductionEvent.objects.count(), 1)
        self.assertEqual(SubmissionAttempt.objects.filter(classification="REJECTED").count(), 1)

    def test_identical_count_is_duplicate_without_double_counting(self):
        event = self.count_event("COUNT-DUP", quantity=12)

        first, second = self.post_events([event, event])

        self.assertEqual(first["status"], "ACCEPTED")
        self.assertEqual(second["status"], "DUPLICATE")
        self.assertEqual(self.summary()["net_total"], 12)
        self.assertEqual(ProductionEvent.objects.count(), 1)
        self.assertEqual(self.summary()["duplicates"], 1)

    def test_void_before_count_resolves_when_count_arrives(self):
        void = {
            "source_id": "LINE-01",
            "event_id": "VOID-EARLY",
            "type": "VOID",
            "quantity": None,
            "target_event_id": "COUNT-LATE",
            "event_time": self.event_time,
        }

        pending_result = self.post_events([void])[0]
        self.assertEqual(pending_result["status"], "PENDING_REFERENCE")
        self.assertEqual(self.summary()["unresolved"], 1)

        count_result = self.post_events([self.count_event("COUNT-LATE", quantity=20)])[0]
        self.assertEqual(count_result["status"], "ACCEPTED")
        resolved_void = ProductionEvent.objects.get(event_id="VOID-EARLY")
        self.assertEqual(resolved_void.status, ProductionEvent.PROCESSED)
        self.assertIsNotNone(resolved_void.acknowledged_at)
        self.assertEqual(self.summary()["unresolved"], 0)
        self.assertEqual(self.summary()["net_total"], 0)

    def test_repeated_acknowledgement_is_idempotent(self):
        self.post_events([self.count_event("COUNT-ACK", quantity=4)])
        body = json.dumps({"event_ids": ["COUNT-ACK"]})

        first = self.client.post("/api/ack", data=body, content_type="application/json")
        second = self.client.post("/api/ack", data=body, content_type="application/json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["results"][0]["status"], "ACKED")
        self.assertEqual(second.json()["results"][0]["status"], "ALREADY_ACKED")
        self.assertEqual(self.summary()["pending_ack"], 0)

    @override_settings(CANDIDATE_ID="CAND-TEST")
    def test_replayed_mqtt_challenge_returns_stored_response_without_reprocessing(self):
        now = timezone.now()
        challenge = {
            "protocol_version": "1.0",
            "candidate_id": "CAND-TEST",
            "challenge_id": "CHALLENGE-REPLAY",
            "command": "PROCESS_EVENTS",
            "expires_at": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "events": [self.count_event("COUNT-MQTT", quantity=9)],
        }
        raw = json.dumps(challenge)

        first = mqtt.handle_challenge_message(raw, candidate_id="CAND-TEST", now=now)["response"]
        replay = mqtt.handle_challenge_message(raw, candidate_id="CAND-TEST", now=now)["response"]

        self.assertEqual(first["status"], "COMPLETED")
        self.assertEqual(first, replay)
        self.assertEqual(ProductionEvent.objects.filter(event_id="COUNT-MQTT").count(), 1)
        self.assertEqual(
            SubmissionAttempt.objects.filter(challenge_id="CHALLENGE-REPLAY").count(),
            1,
        )
        self.assertEqual(MqttChallenge.objects.count(), 1)
        self.assertEqual(first["state"]["net_total"], 9)
        self.assertEqual(first["state"]["rejected_submissions"], 0)

    def test_conflicting_event_id_preserves_original_count(self):
        original = self.count_event("COUNT-CONFLICT", quantity=8)
        changed = self.count_event("COUNT-CONFLICT", quantity=30)

        accepted, conflict = self.post_events([original, changed])

        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertEqual(conflict["status"], "CONFLICT")
        self.assertEqual(self.summary()["net_total"], 8)
        self.assertEqual(self.summary()["conflicts"], 1)
        self.assertEqual(ProductionEvent.objects.count(), 1)

    def test_rejected_only_source_is_filterable(self):
        rejected_source = "LINE-REJECTED-ONLY"
        result = self.post_events(
            [self.count_event("COUNT-REJECTED-ONLY", quantity=501, source_id=rejected_source)]
        )[0]

        self.assertEqual(result["status"], "REJECTED")
        state = self.summary(source_id=rejected_source)
        self.assertEqual(state["net_total"], 0)
        self.assertEqual(state["rejected_submissions"], 1)
        self.assertIn(rejected_source, state["sources"])
        exceptions = self.client.get(
            "/api/state",
            {"view": "exceptions", "source_id": rejected_source},
        )
        self.assertEqual(exceptions.status_code, 200)
        self.assertEqual(exceptions.json()["count"], 1)

    @override_settings(CANDIDATE_ID="CAND-TEST")
    def test_mqtt_count_over_500_is_rejected_without_changing_total(self):
        now = timezone.now()
        challenge = {
            "protocol_version": "1.0",
            "candidate_id": "CAND-TEST",
            "challenge_id": "CHALLENGE-COUNT-501",
            "command": "PROCESS_EVENTS",
            "expires_at": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "events": [self.count_event("COUNT-MQTT-501", quantity=501)],
        }

        response = mqtt.handle_challenge_message(
            json.dumps(challenge), candidate_id="CAND-TEST", now=now
        )["response"]

        self.assertEqual(response["status"], "COMPLETED")
        self.assertEqual(response["results"][0]["status"], "REJECTED")
        self.assertEqual(response["state"]["net_total"], 0)
        self.assertEqual(response["state"]["rejected_submissions"], 1)
        self.assertEqual(ProductionEvent.objects.count(), 0)
