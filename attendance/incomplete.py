"""Maintain incomplete occurrence identity on every effective-value change."""

from django.utils import timezone

from .models import BreakInterval, IncompleteOccurrence, WorkSession


def sync_incomplete_occurrences(session, *, now=None):
    now = now or timezone.now()
    active = session.status != WorkSession.Status.NO_RECORD and session.clock_in_at is not None
    desired = set()
    if active and session.clock_out_at is None:
        desired.add(IncompleteOccurrence.Kind.CLOCK_OUT)
    if active and BreakInterval.objects.filter(
        work_session=session, ended_at__isnull=True,
    ).exists():
        desired.add(IncompleteOccurrence.Kind.BREAK_END)
    open_occurrences = {
        item.kind: item for item in IncompleteOccurrence.objects.select_for_update().filter(
            work_session=session, ended_at__isnull=True,
        )
    }
    for kind, occurrence in open_occurrences.items():
        if kind not in desired:
            occurrence.ended_at = now
            occurrence.save(update_fields=["ended_at"])
    for kind in desired - set(open_occurrences):
        IncompleteOccurrence.objects.create(
            work_session=session, kind=kind, started_at=now,
        )
