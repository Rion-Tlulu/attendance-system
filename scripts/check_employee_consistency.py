"""社員情報と在籍情報の不一致を読み取り専用で確認。"""

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

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist


def main():
    Employee = get_user_model()

    total = 0
    missing_info = 0
    department_mismatch = 0
    hire_mismatch = 0
    leave_mismatch = 0

    for employee in Employee.objects.select_related("employement_info").iterator(
        chunk_size=200
    ):
        total += 1

        try:
            # 現在の関連名の綴りに合わせる
            info = employee.employement_info

        except ObjectDoesNotExist:
            missing_info += 1
            continue

        employee_department = getattr(employee, "department", "") or ""

        info_department = info.department or ""

        if employee_department != info_department:
            department_mismatch += 1

        if getattr(employee, "hire_date", None) != info.hire_date:
            hire_mismatch += 1

        if getattr(employee, "retirement_date", None) != info.leave_date:
            leave_mismatch += 1

    print(f"対象社員={total}")
    print(f"在籍情報なし={missing_info}")
    print(f"部署の不一致={department_mismatch}")
    print(f"入社日の不一致={hire_mismatch}")
    print(f"退職日の不一致={leave_mismatch}")

    print("※このスクリプトはDBを書き換えません。")


if __name__ == "__main__":
    main()
