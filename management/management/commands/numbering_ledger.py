"""部署・番号のDB外保全を初期化、照合、復元する。"""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from management.numbering_ledger import (
    NumberingLedgerError, export_snapshot, reconcile_pending,
    restore_departments, verify_snapshot,
)


class Command(BaseCommand):
    help = "番号保全記録をDBとは別のファイルで管理します。"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["initialize", "verify", "restore", "reconcile"])
        parser.add_argument("--path")
        parser.add_argument("--actor-number")
        parser.add_argument("--reason")

    def handle(self, *args, **options):
        path = Path(options["path"] or settings.NUMBERING_LEDGER_PATH)
        try:
            if options["action"] == "initialize":
                if path.exists():
                    raise NumberingLedgerError("保全記録は既に存在します。上書きはできません。")
                payload = export_snapshot(path)
            elif options["action"] == "verify":
                payload = verify_snapshot(path)
            elif options["action"] == "restore":
                number = options["actor_number"]
                if not number:
                    raise NumberingLedgerError("復元の実行者番号を指定してください。")
                actor = get_user_model().objects.filter(employee_number=number).first()
                if actor is None:
                    raise NumberingLedgerError("復元実行者が見つかりません。")
                payload = restore_departments(path=path, actor=actor)
            else:
                number = options["actor_number"]
                if not number:
                    raise NumberingLedgerError("再開の実行者番号を指定してください。")
                actor = get_user_model().objects.filter(employee_number=number).first()
                if actor is None:
                    raise NumberingLedgerError("再開実行者が見つかりません。")
                payload = reconcile_pending(
                    path=path, actor=actor, reason=options["reason"] or "",
                )
        except NumberingLedgerError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"{options['action']} 完了: 部署{len(payload['departments'])}件、番号履歴{len(payload['numbers'])}件"
        ))
