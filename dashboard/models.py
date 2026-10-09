from django.db import models
from django.db.models import Q


class ProductionSource(models.Model):
    """A factory line or machine that submits production events."""

    source_id = models.TextField(primary_key=True)
    display_name = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["source_id"]

    def __str__(self):
        return self.display_name or self.source_id


class ProductionEvent(models.Model):
    COUNT = "COUNT"
    VOID = "VOID"
    PROCESSED = "PROCESSED"
    PENDING_REFERENCE = "PENDING_REFERENCE"

    source = models.ForeignKey(ProductionSource, on_delete=models.PROTECT, related_name="events")
    event_id = models.TextField(db_index=True)
    type = models.CharField(max_length=8, choices=[(COUNT, COUNT), (VOID, VOID)])
    quantity = models.IntegerField(null=True, blank=True)
    target_event_id = models.TextField(null=True, blank=True)
    event_time = models.DateTimeField()
    status = models.CharField(
        max_length=24,
        choices=[(PROCESSED, PROCESSED), (PENDING_REFERENCE, PENDING_REFERENCE)],
    )
    normalized = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["received_at", "id"]
        indexes = [models.Index(fields=["status"], name="idx_event_status")]
        constraints = [
            models.UniqueConstraint(fields=["source", "event_id"], name="uq_event_per_source"),
            models.UniqueConstraint(
                fields=["source", "target_event_id"],
                condition=Q(type="VOID"),
                name="uq_one_void_per_count",
            ),
            models.CheckConstraint(
                condition=(
                    Q(type="COUNT", quantity__gt=0, target_event_id__isnull=True, status="PROCESSED")
                    | Q(
                        type="VOID",
                        quantity__isnull=True,
                        target_event_id__isnull=False,
                        status__in=["PROCESSED", "PENDING_REFERENCE"],
                    )
                ),
                name="chk_production_event_shape",
            ),
        ]

    def __str__(self):
        return f"{self.source_id} / {self.event_id} ({self.type})"


class SubmissionAttempt(models.Model):
    REST = "REST"
    MQTT = "MQTT"
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    PENDING_REFERENCE = "PENDING_REFERENCE"
    REJECTED = "REJECTED"

    channel = models.CharField(max_length=8, default=REST)
    challenge_id = models.TextField(null=True, blank=True)
    payload = models.JSONField(null=True, blank=True)
    source_id = models.TextField(null=True, blank=True, db_index=True)
    event_id = models.TextField(null=True, blank=True, db_index=True)
    classification = models.CharField(
        max_length=24,
        choices=[
            (ACCEPTED, ACCEPTED),
            (DUPLICATE, DUPLICATE),
            (CONFLICT, CONFLICT),
            (PENDING_REFERENCE, PENDING_REFERENCE),
            (REJECTED, REJECTED),
        ],
        db_index=True,
    )
    error = models.TextField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at", "-id"]

    def __str__(self):
        return f"{self.classification}: {self.event_id or 'unknown event'}"


class MqttChallenge(models.Model):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    challenge_id = models.TextField(primary_key=True)
    request_digest = models.CharField(max_length=64)
    request_body = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=12)
    error_code = models.CharField(max_length=64, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    response = models.JSONField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.challenge_id} ({self.status})"


class MqttRuntimeState(models.Model):
    """Single shared row so the web process can display worker connection state."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    candidate_id = models.TextField(blank=True)
    broker = models.TextField(blank=True)
    connected = models.BooleanField(default=False)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    last_connect_error = models.TextField(null=True, blank=True)
    last_error = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"MQTT runtime ({'online' if self.connected else 'offline'})"
