"""STEP6: テンプレート・CSS・Django設定の確認。"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()

from django.contrib.staticfiles.finders import find
from django.core.management import call_command
from django.template.loader import get_template

TEMPLATES = (
    "accounts/login.html",
    "accounts/overview.html",
    "employee/home.html",
    "employee/monthly.html",
    "employee/daily.html",
    "corrections/form.html",
    "corrections/confirm.html",
    "corrections/detail.html",
    "management/attendance_list.html",
    "management/employee_list.html",
    "management/audit_history.html",
    "management/employee_month.html",
)


STATIC_FILES = (
    "css/app.css",
    "css/correction-list.css",
    "css/employee-clock.css",
    "css/employee-monthly.css",
    "css/account-pages.css",
    "css/daily-record-correction.css",
    "css/manager-attendance-list.css",
    "css/manager-employee-directory.css",
    "css/manager-audit-export.css",
    "css/manager-pages.css",
    "js/app.js",
)


def main():
    errors = []

    # テンプレートの読み込みと構文確認
    for name in TEMPLATES:
        try:
            get_template(name)

        except Exception as exc:
            errors.append(f"TEMPLATE {name}: " f"{type(exc).__name__}: {exc}")

    # 静的ファイルの配置確認
    for name in STATIC_FILES:
        if find(name) is None:
            errors.append(f"STATIC {name}: 見つかりません")

    # Django全体のシステムチェック
    try:
        call_command(
            "check",
            verbosity=0,
        )

    except Exception as exc:
        errors.append(f"DJANGO CHECK: " f"{type(exc).__name__}: {exc}")

    if errors:
        for error in errors:
            print("NG", error)

        return 1

    print("OK: 全テンプレートの構文・" "静的ファイル配置・Django設定")

    return 0


if __name__ == "__main__":
    sys.exit(main())
