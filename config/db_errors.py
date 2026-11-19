"""DB の保存失敗時の共通案内（要件定義書 11章）。

SQLite のロック待ちの上限超過（OperationalError）や一意制約違反（IntegrityError）で
更新が反映されなかった場合は、部分保存せず、成功とも表示しない。
呼び出し側は atomic の外で捕捉し、結果の確認と再操作を案内する。
"""

import logging

from django.db import IntegrityError, OperationalError

SAVE_FAILURE_ERRORS = (IntegrityError, OperationalError)

UNCONFIRMED_SAVE_MESSAGE = (
    "保存結果を確認できませんでした。"
    "最新の状態を確認してから、必要な場合は操作をやり直してください。"
)

logger = logging.getLogger("attendance.db")


def log_save_failure(operation, **context):
    """失敗した操作を記録する。認証情報や平文パスワードは渡さない。"""

    logger.exception("DBの保存に失敗しました: %s %s", operation, context)
