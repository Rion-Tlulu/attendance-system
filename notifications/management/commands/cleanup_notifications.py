"""90日を超えた通知だけを削除する日次コマンド。"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications.models import Notification


class Command(BaseCommand):
    help = "作成から90日を超えた通知のみ削除します。"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=90)
        old = Notification.objects.filter(created_at__lt=cutoff)
        count = old.count()
        if not options["dry_run"]:
            old.delete()
        self.stdout.write(f"対象通知={count} dry_run={options['dry_run']}")
