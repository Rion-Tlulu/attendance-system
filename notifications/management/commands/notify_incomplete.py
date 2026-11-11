"""Notify each recipient once per unresolved incomplete occurrence."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from attendance.incomplete import sync_incomplete_occurrences
from attendance.models import IncompleteOccurrence, WorkSession
from notifications.models import Notification
from notifications.services import create_notification


class Command(BaseCommand):
    help = "前日以前から続く未完了勤務を本人と業務管理者へ通知します。"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=1)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--max-new", type=int, default=500)

    def handle(self, *args, **options):
        days, maximum = options["days"], options["max_new"]
        if days < 1 or maximum < 1:
            raise CommandError("--days と --max-new は1以上にしてください。")
        cutoff = timezone.localdate() - timedelta(days=days)
        # Also cover sessions loaded directly during an import or a migration.
        discovery_ids = WorkSession.objects.filter(
            status__in=(WorkSession.Status.WORKING, WorkSession.Status.ON_BREAK),
            work_date__lte=cutoff,
        ).values_list("pk", flat=True).iterator() if not options["dry_run"] else ()
        for session_pk in discovery_ids:
            with transaction.atomic():
                session = WorkSession.objects.select_for_update().get(pk=session_pk)
                had_history = IncompleteOccurrence.objects.filter(work_session=session).exists()
                if not options["dry_run"]:
                    sync_incomplete_occurrences(session)
                if not had_history and session.incomplete_notified_version is not None:
                    IncompleteOccurrence.objects.filter(
                        work_session=session, ended_at__isnull=True,
                    ).update(recipients_selected=True)
        occurrence_ids = list(IncompleteOccurrence.objects.filter(
            ended_at__isnull=True, work_session__work_date__lte=cutoff,
        ).order_by("work_session__work_date", "pk").values_list("pk", flat=True))
        Employee = get_user_model()
        created_count = eligible_count = skipped_count = 0

        for occurrence_pk in occurrence_ids:
            if created_count >= maximum:
                break
            with transaction.atomic():
                reference = IncompleteOccurrence.objects.get(pk=occurrence_pk)
                session = WorkSession.objects.select_for_update().select_related("employee").get(
                    pk=reference.work_session_id,
                )
                if not options["dry_run"]:
                    sync_incomplete_occurrences(session)
                occurrence = IncompleteOccurrence.objects.select_for_update().get(pk=occurrence_pk)
                if occurrence.ended_at is not None:
                    skipped_count += 1
                    continue
                if not occurrence.recipients_selected:
                    recipients = list(Employee.objects.filter(
                        is_active=True, is_business_admin=True,
                    ).exclude(pk=session.employee_id).values_list("pk", flat=True))
                    if session.employee.is_active:
                        recipients.insert(0, session.employee_id)
                    if not options["dry_run"]:
                        occurrence.recipient_ids = recipients
                        occurrence.recipients_selected = True
                        occurrence.save(update_fields=["recipient_ids", "recipients_selected"])
                else:
                    recipients = occurrence.recipient_ids
                pending = [pk for pk in recipients if pk not in occurrence.notified_recipient_ids]
                eligible_count += len(pending)
                if options["dry_run"]:
                    continue
                notified = list(occurrence.notified_recipient_ids)
                for recipient_id in pending:
                    if created_count >= maximum:
                        break
                    recipient = Employee.objects.filter(pk=recipient_id, is_active=True).first()
                    if recipient is None:
                        notified.append(recipient_id)
                        continue
                    is_management = recipient_id != session.employee_id
                    target = (
                        reverse("management:employee_month", args=[
                            session.employee_id, session.work_date.year, session.work_date.month,
                        ]) if is_management else reverse("attendance:daily", args=[
                            session.work_date.year, session.work_date.month, session.work_date.day,
                        ])
                    )
                    key = f"incomplete:{occurrence.occurrence_id}:{occurrence.kind}:{recipient_id}"
                    existed = Notification.objects.filter(event_key=key).exists()
                    create_notification(
                        recipient=recipient, kind=Notification.Kind.INCOMPLETE,
                        title="未完了の勤務があります",
                        body=(
                            f"{session.employee.get_full_name()}（{session.employee.employee_number}）の"
                            if is_management else ""
                        ) + f"{session.work_date:%Y/%m/%d}の勤務記録が未完了です。継続勤務の可能性も含めて確認してください。",
                        target_path=target, event_key=key, is_management=is_management,
                    )
                    notified.append(recipient_id)
                    created_count += not existed
                occurrence.notified_recipient_ids = notified
                occurrence.save(update_fields=["notified_recipient_ids"])
        self.stdout.write(
            f"対象={eligible_count} 新規通知={created_count} 除外={skipped_count} "
            f"dry_run={options['dry_run']}"
        )
