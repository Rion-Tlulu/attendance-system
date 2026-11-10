"""本番 PostgreSQL の日次カスタム形式バックアップ。

POSTGRES_* 接続変数と BACKUP_DIR を設定して実行する。
秘密情報はコマンドライン引数に渡さない。
"""

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def main():
    required = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST", "BACKUP_DIR")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"必要な環境変数がありません: {', '.join(missing)}")
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise SystemExit("pg_dump が PATH に見つかりません")

    backup_dir = Path(os.environ["BACKUP_DIR"]).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = backup_dir / f"attendance-{stamp}.dump"
    if destination.exists():
        raise SystemExit("同名のバックアップが既にあります")
    fd, temporary = tempfile.mkstemp(prefix=".attendance-", suffix=".partial", dir=backup_dir)
    os.close(fd)
    env = os.environ.copy()
    env.update({
        "PGDATABASE": env["POSTGRES_DB"],
        "PGUSER": env["POSTGRES_USER"],
        "PGPASSWORD": env["POSTGRES_PASSWORD"],
        "PGHOST": env["POSTGRES_HOST"],
        "PGPORT": env.get("POSTGRES_PORT", "5432"),
        "PGSSLMODE": env.get("POSTGRES_SSLMODE", "verify-full"),
    })
    try:
        subprocess.run(
            [pg_dump, "--format=custom", "--no-owner", f"--file={temporary}"],
            check=True, env=env,
        )
        if not Path(temporary).stat().st_size:
            raise RuntimeError("バックアップが空です")
        os.replace(temporary, destination)
        print(f"バックアップ完了: {destination.name} ({destination.stat().st_size} bytes)")
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, OSError, RuntimeError) as exc:
        print(f"バックアップ失敗: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
