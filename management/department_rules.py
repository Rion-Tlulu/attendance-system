import re

from django.core.exceptions import ValidationError

from .models import (
    Department,
    DepartmentRegistration,
    EmployeeNumberHistory,
)

from accounts.models import Employee


def normalize_department_name(value):
    """部署名の前後の空白を除去する。"""
    name = (value or "").strip()

    if not name:
        raise ValidationError("部署名を入力してください。")

    if len(name) > 100:
        raise ValidationError("部署名は100文字以内です。")

    return name


def used_department_codes():
    """現在・過去の利用実績から使用済みコードを取得する。"""

    used = set(Department.objects.values_list("code", flat=True))

    used.update(DepartmentRegistration.objects.values_list("code", flat=True))

    for number in Employee.objects.values_list("employee_number", flat=True):
        if re.fullmatch(r"[1-9][0-9]{4}", number or ""):
            used.add(int(number[0]))

    for number in EmployeeNumberHistory.objects.values_list(
        "employee_number", flat=True
    ):
        if re.fullmatch(r"[1-9][0-9]{4}", number or ""):
            used.add(int(number[0]))

    return used


def available_department_codes():
    """新しい部署に割当可能なコードを返す。"""
    used = used_department_codes()
    return [code for code in range(1, 10) if code not in used]
