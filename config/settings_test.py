"""テスト専用設定。

manage.py test では DJANGO_SETTINGS_MODULE が未指定の場合に自動で使用する。
本番と同じ DATABASES（OPTIONS を含む）を引き継ぎ、テスト用 DB だけをファイルにする。

- インメモリのテスト DB は共有キャッシュでテーブル単位にロックされ、
  busy timeout も効かないため、本番の SQLite と同じロック挙動を検証できない。
- テスト用 DB 名は相対パスで test_ から始める。
  management.numbering_ledger._test_database() がこの接頭辞でテスト DB を判定するため。
- 番号保全台帳の既定パスも一時フォルダへ向け、本物の台帳に触れないようにする。
"""

import copy
import tempfile
from pathlib import Path

from .settings import *  # noqa: F401,F403
from .settings import DATABASES as _BASE_DATABASES

DATABASES = copy.deepcopy(_BASE_DATABASES)

if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES["default"]["TEST"] = {"NAME": "test_attendance_v156.sqlite3"}

NUMBERING_LEDGER_PATH = (
    Path(tempfile.gettempdir()) / "attendance_v156_test" / "numbering-ledger.json"
)

# テストでは検証の速さを優先する（本番の PBKDF2 は重く、ユーザー作成のたびに時間がかかる）。
# パスワードのハッシュ化そのものを検証するテストは、使用中のハッシャー名ではなく
# 「平文で保存されていない」ことを確認しているため影響しない。
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
