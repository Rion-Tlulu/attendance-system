"""未完了勤務を本人に一度だけ通知する管理コマンド。"""

from datetime import timedelta

from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django.urls import reverse
from django.utils import timezone

from attendance.models import (
    MonthlyClosing,
    WorkSession,
)
from corrections.models import CorrectionRequest
from notifications.models import Notification


class Command(BaseCommand):
    help = "一定日数前の未完了勤務を本人に通知します。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=2,
            help="何日以上前の勤務を対象とするか",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="通知を書き込まず対象を確認する",
        )

        parser.add_argument(
            "--max-new",
            type=int,
            default=500,
            help="1回に作成する通知の上限",
        )

    def handle(self, *args, **options):

        days = options["days"]
        maximum = options["max_new"]

        if days < 1 or maximum < 1:
            raise CommandError("--days と --max-new は" "1以上にしてください。")

        if not hasattr(
            Notification.Kind,
            "INCOMPLETE",
        ):
            raise CommandError(
                "Notification.Kind.INCOMPLETE がありません。"
                "notifications/models.py の Kind に"
                "追加してから実行してください。"
            )

        cutoff = timezone.localdate() - timedelta(days=days)

        # アカウントが有効で、
        # 勤務中または休憩中のままの記録を取得。
        sessions = (
            WorkSession.objects.filter(
                status__in=(
                    WorkSession.Status.WORKING,
                    WorkSession.Status.ON_BREAK,
                ),
                work_date__lte=cutoff,
                employee__is_active=True,
            )
            .select_related("employee")
            .order_by("work_date", "pk")
        )

        created_count = 0
        eligible_count = 0
        skipped_count = 0

        for session in sessions.iterator(chunk_size=200):

            # 審査中の修正申請があれば通知しない。
            has_pending_request = CorrectionRequest.objects.filter(
                work_session=session,
                status=CorrectionRequest.Status.PENDING,
            ).exists()

            if has_pending_request:
                skipped_count += 1
                continue

            # 対象月が確定済みなら通知しない。
            is_finalized = MonthlyClosing.objects.filter(
                employee_id=session.employee_id,
                target_month=(session.work_date.replace(day=1)),
                status=MonthlyClosing.Status.FINALIZED,
            ).exists()

            if is_finalized:
                skipped_count += 1
                continue

            # 勤務IDごとに重複を防止する。
            event_key = f"incomplete:{session.pk}"

            already_notified = Notification.objects.filter(
                event_key=event_key,
            ).exists()

            if already_notified:
                skipped_count += 1
                continue

            eligible_count += 1

            # dry-runではDBへ書き込まない。
            if options["dry_run"]:
                continue

            target_path = reverse(
                "attendance:daily",
                args=[
                    session.work_date.year,
                    session.work_date.month,
                    session.work_date.day,
                ],
            )

            # event_keyにはユニーク制約がある前提。
            # 同時実行時の重複もDB側で防ぐ。
            _, created = Notification.objects.get_or_create(
                event_key=event_key,
                defaults={
                    "recipient": session.employee,
                    "kind": (Notification.Kind.INCOMPLETE),
                    "title": ("未完了の勤怠があります"),
                    "body": (
                        f"{session.work_date:%Y/%m/%d}"
                        "の勤務記録が未完了です。"
                        "内容をご確認ください。"
                    ),
                    "target_path": target_path,
                },
            )

            if created:
                created_count += 1

            if created_count >= maximum:
                break

        self.stdout.write(
            f"対象候補={eligible_count} "
            f"新規通知={created_count} "
            f"除外済み={skipped_count} "
            f"dry_run={options['dry_run']}"
        )
