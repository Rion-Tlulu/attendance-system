"""Detach corrections from proven legacy placeholders for no-record days."""

from django.db import migrations


def convert_legacy_empty_sessions(apps, schema_editor):
    Session = apps.get_model("attendance", "WorkSession")
    Correction = apps.get_model("corrections", "CorrectionRequest")
    ClockEvent = apps.get_model("attendance", "ClockEvent")
    BreakInterval = apps.get_model("attendance", "BreakInterval")
    Occurrence = apps.get_model("attendance", "IncompleteOccurrence")
    AuditLog = apps.get_model("auditlog", "AuditLog")
    database = schema_editor.connection.alias

    candidates = Session.objects.using(database).filter(
        status="no_record", version=1,
        clock_in_at__isnull=True, clock_out_at__isnull=True,
        moved_to__isnull=True,
    )
    for session in candidates.iterator():
        related = list(Correction.objects.using(database).filter(work_session_id=session.pk))
        if not related or any(
            item.original_version != 1 or item.status not in {"pending", "returned", "withdrawn"}
            for item in related
        ):
            continue
        if (ClockEvent.objects.using(database).filter(work_session_id=session.pk).exists()
                or BreakInterval.objects.using(database).filter(work_session_id=session.pk).exists()
                or Occurrence.objects.using(database).filter(work_session_id=session.pk).exists()
                or Session.objects.using(database).filter(moved_to_id=session.pk).exists()
                or AuditLog.objects.using(database).filter(
                    target_model="WorkSession", target_id=str(session.pk),
                ).exists()):
            continue
        # The old submit path created a version-1 empty session and logged
        # empty effective values. Require that audit evidence before removing it.
        evidenced = False
        for item in related:
            for log in AuditLog.objects.using(database).filter(
                action="correction_submit", target_model="CorrectionRequest",
                target_id=str(item.pk),
            ):
                values = log.before_data
                if (isinstance(values, dict)
                        and values.get("clock_in_at") is None
                        and values.get("clock_out_at") is None
                        and values.get("breaks") == []
                        and isinstance(log.details, dict)
                        and log.details.get("original_version") == 1):
                    evidenced = True
                    break
            if evidenced:
                break
        if not evidenced:
            continue
        Correction.objects.using(database).filter(work_session_id=session.pk).update(
            work_session_id=None, original_version=None,
        )
        Session.objects.using(database).filter(pk=session.pk).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("corrections", "0003_correctionrequest_employee_and_more"),
        ("auditlog", "0003_alter_auditlog_action"),
    ]

    operations = [migrations.RunPython(convert_legacy_empty_sessions)]
