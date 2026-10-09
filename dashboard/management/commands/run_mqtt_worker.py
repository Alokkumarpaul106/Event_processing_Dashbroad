from django.core.management.base import BaseCommand, CommandError

from dashboard.mqtt import run_worker


class Command(BaseCommand):
    help = "Connect to the configured MQTT broker and process production challenges."

    def handle(self, *args, **options):
        try:
            run_worker()
        except (OSError, ValueError, RuntimeError) as exc:
            raise CommandError(str(exc)) from exc
