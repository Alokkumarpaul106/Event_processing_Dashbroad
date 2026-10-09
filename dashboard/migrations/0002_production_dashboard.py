from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("dashboard", "0001_initial")]

    operations = [
        migrations.DeleteModel(name="DeviceEvent"),
        migrations.CreateModel(
            name="ProductionSource",
            fields=[
                ("source_id", models.TextField(primary_key=True, serialize=False)),
                ("display_name", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["source_id"]},
        ),
        migrations.CreateModel(
            name="ProductionEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_id", models.TextField(db_index=True)),
                ("type", models.CharField(choices=[("COUNT", "COUNT"), ("VOID", "VOID")], max_length=8)),
                ("quantity", models.IntegerField(blank=True, null=True)),
                ("target_event_id", models.TextField(blank=True, null=True)),
                ("event_time", models.DateTimeField()),
                ("status", models.CharField(choices=[("PROCESSED", "PROCESSED"), ("PENDING_REFERENCE", "PENDING_REFERENCE")], max_length=24)),
                ("normalized", models.JSONField()),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="dashboard.productionsource")),
            ],
            options={"ordering": ["received_at", "id"]},
        ),
        migrations.AddConstraint(
            model_name="productionevent",
            constraint=models.UniqueConstraint(fields=("source", "event_id"), name="uq_event_per_source"),
        ),
        migrations.AddConstraint(
            model_name="productionevent",
            constraint=models.UniqueConstraint(condition=Q(type="VOID"), fields=("source", "target_event_id"), name="uq_one_void_per_count"),
        ),
        migrations.AddConstraint(
            model_name="productionevent",
            constraint=models.CheckConstraint(
                condition=(
                    Q(type="COUNT", quantity__gt=0, target_event_id__isnull=True, status="PROCESSED")
                    | Q(type="VOID", quantity__isnull=True, target_event_id__isnull=False, status__in=["PROCESSED", "PENDING_REFERENCE"])
                ),
                name="chk_production_event_shape",
            ),
        ),
        migrations.AddIndex(
            model_name="productionevent",
            index=models.Index(fields=["status"], name="idx_event_status"),
        ),
        migrations.CreateModel(
            name="SubmissionAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("channel", models.CharField(default="REST", max_length=8)),
                ("challenge_id", models.TextField(blank=True, null=True)),
                ("payload", models.JSONField(blank=True, null=True)),
                ("source_id", models.TextField(blank=True, db_index=True, null=True)),
                ("event_id", models.TextField(blank=True, db_index=True, null=True)),
                ("classification", models.CharField(choices=[("ACCEPTED", "ACCEPTED"), ("DUPLICATE", "DUPLICATE"), ("CONFLICT", "CONFLICT"), ("PENDING_REFERENCE", "PENDING_REFERENCE"), ("REJECTED", "REJECTED")], db_index=True, max_length=24)),
                ("error", models.TextField(blank=True, null=True)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-received_at", "-id"]},
        ),
        migrations.CreateModel(
            name="MqttChallenge",
            fields=[
                ("challenge_id", models.TextField(primary_key=True, serialize=False)),
                ("request_digest", models.CharField(max_length=64)),
                ("request_body", models.JSONField(blank=True, null=True)),
                ("status", models.CharField(max_length=12)),
                ("error_code", models.CharField(blank=True, max_length=64, null=True)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("response", models.JSONField(blank=True, null=True)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-received_at"]},
        ),
        migrations.CreateModel(
            name="MqttRuntimeState",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("candidate_id", models.TextField(blank=True)),
                ("broker", models.TextField(blank=True)),
                ("connected", models.BooleanField(default=False)),
                ("last_heartbeat_at", models.DateTimeField(blank=True, null=True)),
                ("last_connect_error", models.TextField(blank=True, null=True)),
                ("last_error", models.JSONField(blank=True, null=True)),
            ],
        ),
    ]
