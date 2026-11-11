import uuid

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def carry_forward(apps, schema_editor):
    Session = apps.get_model("attendance", "WorkSession")
    Occurrence = apps.get_model("attendance", "IncompleteOccurrence")
    Notification = apps.get_model("notifications", "Notification")
    for session in Session.objects.filter(status__in=["working", "on_break"]).iterator():
        previously_notified = session.incomplete_notified_version is not None
        legacy_recipients = []
        if previously_notified:
            prefix = f"incomplete:{session.pk}:v{session.incomplete_notified_version}:"
            legacy_recipients = list(Notification.objects.filter(
                event_key__startswith=prefix,
            ).values_list("recipient_id", flat=True).distinct())
        Occurrence.objects.create(
            occurrence_id=uuid.uuid4(), work_session_id=session.pk,
            kind="clock_out", started_at=session.clock_in_at or session.created_at,
            recipients_selected=previously_notified,
            recipient_ids=legacy_recipients,
            notified_recipient_ids=legacy_recipients,
        )
        if session.status == "on_break":
            Occurrence.objects.create(
                occurrence_id=uuid.uuid4(), work_session_id=session.pk,
                kind="break_end", started_at=session.clock_in_at or session.created_at,
                recipients_selected=previously_notified,
                recipient_ids=legacy_recipients,
                notified_recipient_ids=legacy_recipients,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0003_worksession_moved_to"),
        ("notifications", "0003_notification_is_management_alter_notification_kind"),
    ]

    operations = [
        migrations.CreateModel(
            name="IncompleteOccurrence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("occurrence_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("kind", models.CharField(choices=[("clock_out", "退勤未記録"), ("break_end", "休憩未終了")], max_length=20)),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("recipient_ids", models.JSONField(default=list)),
                ("notified_recipient_ids", models.JSONField(default=list)),
                ("recipients_selected", models.BooleanField(default=False)),
                ("work_session", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name="incomplete_occurrences", to="attendance.worksession")),
            ],
        ),
        migrations.AddConstraint(
            model_name="incompleteoccurrence",
            constraint=models.UniqueConstraint(
                condition=models.Q(ended_at__isnull=True), fields=("work_session", "kind"),
                name="unique_open_incomplete_occurrence",
            ),
        ),
        migrations.RunPython(carry_forward, migrations.RunPython.noop),
    ]
