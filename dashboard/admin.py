from django.contrib import admin

from .models import MqttChallenge, ProductionEvent, ProductionSource, SubmissionAttempt


@admin.register(ProductionSource)
class ProductionSourceAdmin(admin.ModelAdmin):
    list_display = ("source_id", "display_name", "created_at")
    search_fields = ("source_id", "display_name")


@admin.register(ProductionEvent)
class ProductionEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "source", "type", "quantity", "status", "received_at", "acknowledged_at")
    list_filter = ("type", "status", "source")
    search_fields = ("event_id", "target_event_id", "source__source_id")
    readonly_fields = ("received_at", "normalized")


@admin.register(SubmissionAttempt)
class SubmissionAttemptAdmin(admin.ModelAdmin):
    list_display = ("event_id", "source_id", "channel", "classification", "received_at")
    list_filter = ("channel", "classification")
    search_fields = ("event_id", "source_id", "challenge_id")
    readonly_fields = ("received_at", "payload")


@admin.register(MqttChallenge)
class MqttChallengeAdmin(admin.ModelAdmin):
    list_display = ("challenge_id", "status", "error_code", "received_at", "published_at")
    list_filter = ("status",)
    search_fields = ("challenge_id", "error_code")
    readonly_fields = ("request_body", "response", "received_at", "responded_at", "published_at")
