"""Post-commit extension points for accepted production changes."""

from django.dispatch import Signal

event_accepted = Signal()
void_resolved = Signal()
event_acknowledged = Signal()
