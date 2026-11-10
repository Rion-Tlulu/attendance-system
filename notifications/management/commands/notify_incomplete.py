"""前日以前の未完了勤務を本人と業務管理者に通知する。毎日09:00 JSTに実行。"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from attendance.models import MonthlyClosing, WorkSession
from corrections.models import CorrectionRequest
from notifications.models import Notification
from notifications.services import create_notification


class Command(BaseCommand):
    help = "前日以前の未完了勤務を本人と業務管理者に通知します。"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=1)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--max-new", type=int, default=500)

    def handle(self, *args, **options):
        days = options["days"]
        maximum = options["max_new"]
        if days < 1 or maximum < 1:
            raise CommandError("--days と --max-new は1以上にしてください。")

        cutoff = timezone.localdate() - timedelta(days=days)
        sessions = (
            WorkSession.objects.filter(
                status__in=(WorkSession.Status.WORKING, WorkSession.Status.ON_BREAK),
                work_date__lte=cutoff,
                employee__is_active=True,
            )
            .select_related("employee")
            .order_by("work_date", "pk")
        )
        Employee = get_user_model()
        managers = list(Employee.objects.filter(is_active=True, is_business_admin=True))
        created_count = eligible_count = skipped_count = 0

        for candidate in sessions.iterator(chunk_size=200):
            if created_count >= maximum:
                break
            if CorrectionRequest.objects.filter(
                work_session=candidate, status=CorrectionRequest.Status.PENDING
            ).exists():
                skipped_count += 1
                continue
            if MonthlyClosing.objects.filter(
                employee_id=candidate.employee_id,
                target_month=candidate.work_date.replace(day=1),
                status=MonthlyClosing.Status.FINALIZED,
            ).exists():
                skipped_count += 1
                continue
            if candidate.incomplete_notified_version is not None:
                skipped_count += 1
                continue

            recipients = [(candidate.employee, False)] + [
                (manager, True) for manager in managers if manager.pk != candidate.employee_id
            ]
            eligible_count += len(recipients)
            if options["dry_run"]:
                continue

            with transaction.atomic():
                session = WorkSession.objects.select_for_update().get(pk=candidate.pk)
                if session.incomplete_notified_version is not None:
                    continue
                target = reverse("attendance:daily", args=[
                    session.work_date.year, session.work_date.month, session.work_date.day,
                ])
                for recipient, is_management in recipients:
                    if created_count >= maximum:
                        break
                    event_key = f"incomplete:{session.pk}:v{session.version}:{recipient.pk}"
                    existed = Notification.objects.filter(event_key=event_key).exists()
                    create_notification(
                        recipient=recipient,
                        kind=Notification.Kind.INCOMPLETE,
                        title="未完了の勤務があります",
                        body=f"{session.work_date:%Y/%m/%d}の勤務記録が未完了です。内容を確認してください。",
                        target_path=(
                            reverse("management:employee_month", args=[
                                session.employee_id, session.work_date.year, session.work_date.month,
                            ])
                            if is_management else target
                        ),
                        event_key=event_key,
                        is_management=is_management,
                    )
                    created_count += not existed
                if all(Notification.objects.filter(
                    event_key=f"incomplete:{session.pk}:v{session.version}:{recipient.pk}"
                ).exists() for recipient, _ in recipients):
                    session.incomplete_notified_version = session.version
                    session.save(update_fields=["incomplete_notified_version"])

        self.stdout.write(
            f"対象={eligible_count} 新規通知={created_count} 除外={skipped_count} "
            f"dry_run={options['dry_run']}"
        )
