
"""
SQLiteデータベースのバックアップ・復元確認。

対応コマンド：
    python scripts/backup_sqlite.py backup
    python scripts/backup_sqlite.py restore-test

目的：
    1. 稼働中のSQLiteデータベースをコピー
    2. コピー後のデータ整合性を確認
    3. 一時環境への復元を検証
    4. 元データベースを変更しない

注意：
    本システムの DB は SQLite（db.sqlite3）だけを使う。
    バックアップには機密情報が含まれます。
"""

import argparse
import os
import sqlite3
import sys
import tempfile

from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import uuid4


# ==========================================
# Djangoの設定
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(
    0,
    str(PROJECT_ROOT),
)

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()

from django.conf import settings


# ==========================================
# バックアップ先
# ==========================================

BACKUP_DIR = (
    Path.home()
    / "attendance_private_backups"
)


# ==========================================
# SQLiteの接続
# ==========================================

def connect_readonly(path):
    """SQLiteを読み取り専用で開く。"""

    path = Path(path).resolve()

    return sqlite3.connect(
        path.as_uri() + "?mode=ro",
        uri=True,
        timeout=30,
    )


# ==========================================
# 現在のDBファイルを取得
# ==========================================

def get_database_path():
    """開発環境のSQLiteデータベースを取得。"""

    database = settings.DATABASES["default"]

    if database["ENGINE"] != "django.db.backends.sqlite3":
        raise RuntimeError(
            "このスクリプトはSQLite専用です。"
        )

    db_name = str(database["NAME"])

    if db_name == ":memory:":
        raise RuntimeError(
            "メモリDBのバックアップには対応していません。"
        )

    db_path = Path(db_name).resolve()

    if not db_path.is_file():
        raise FileNotFoundError(
            "SQLiteデータベースが見つかりません。"
        )

    return db_path


# ==========================================
# 整合性確認
# ==========================================

def check_integrity(db_path):
    """
    データベースの構造を検証する。

    戻り値：
        テーブル数
    """

    with closing(connect_readonly(db_path)) as conn:

        result = conn.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if result is None or result[0] != "ok":
            raise RuntimeError(
                "SQLite整合性チェックに失敗しました。"
            )

        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchone()[0]

        if count == 0:
            raise RuntimeError(
                "テーブルが存在しません。"
            )

        return count


# ==========================================
# バックアップ処理
# ==========================================

def create_backup():
    """SQLiteのオンラインバックアップを作成。"""

    source_path = get_database_path()

    BACKUP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    backup_name = (
        f"attendance_{timestamp}_"
        f"{uuid4().hex[:8]}.sqlite3"
    )

    destination_path = BACKUP_DIR / backup_name

    try:
        with closing(
            connect_readonly(source_path)
        ) as source:

            with closing(
                sqlite3.connect(
                    str(destination_path),
                    timeout=30,
                )
            ) as destination:

                source.backup(
                    destination,
                    pages=128,
                    sleep=0.25,
                )

        table_count = check_integrity(
            destination_path
        )

        if destination_path.stat().st_size == 0:
            raise RuntimeError(
                "バックアップファイルが空です。"
            )

    except Exception:
        # 作成失敗時の不完全ファイルを削除
        destination_path.unlink(
            missing_ok=True
        )
        raise

    print("バックアップ成功")
    print("保存先:", destination_path)
    print("テーブル数:", table_count)
    print("整合性チェック: OK")

    return destination_path


# ==========================================
# 最新バックアップの検索
# ==========================================

def get_latest_backup():
    """保存済みの最新バックアップを取得。"""

    backups = list(
        BACKUP_DIR.glob(
            "attendance_*.sqlite3"
        )
    )

    if not backups:
        raise FileNotFoundError(
            "バックアップが見つかりません。"
        )

    return max(
        backups,
        key=lambda path: path.stat().st_mtime,
    )


# ==========================================
# 復元テスト
# ==========================================

def restore_test():
    """
    バックアップを一時ファイルへ復元する。

    元のdb.sqlite3は変更しない。
    """

    backup_path = get_latest_backup()

    original_table_count = check_integrity(
        backup_path
    )

    with tempfile.TemporaryDirectory(
        prefix="attendance_restore_test_"
    ) as temp_directory:

        restore_path = (
            Path(temp_directory)
            / "restored.sqlite3"
        )

        with closing(
            connect_readonly(backup_path)
        ) as source:

            with closing(
                sqlite3.connect(
                    str(restore_path)
                )
            ) as destination:

                source.backup(destination)

        restored_table_count = check_integrity(
            restore_path
        )

        if restored_table_count != original_table_count:
            raise RuntimeError(
                "復元後のテーブル数が一致しません。"
            )

        print("復元テスト成功")
        print("復元元:", backup_path)
        print("テーブル数:", restored_table_count)
        print("整合性チェック: OK")

    print(
        "一時ファイルを削除しました。"
        "元のデータベースは変更していません。"
    )


# ==========================================
# 実行コマンド
# ==========================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "SQLiteバックアップ・復元テスト"
        )
    )

    parser.add_argument(
        "command",
        choices=[
            "backup",
            "restore-test",
        ],
        help="実行する操作",
    )

    args = parser.parse_args()

    if args.command == "backup":
        create_backup()

    elif args.command == "restore-test":
        restore_test()


if __name__ == "__main__":
    main()
