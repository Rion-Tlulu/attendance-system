"""部署別の社員番号候補と発行処理。"""

import re

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .models import Department, EmployeeNumberHistory
from .numbering_ledger import require_numbering_ready


def next_employee_number(department):
    """現行番号と発行履歴の最大連番より次の番号を返す。

    呼び出し側は保存時に Department 行を select_for_update でロックする。
    この候補は予約ではないため、表示後に変わる場合がある。
    """
    require_numbering_ready()
    if not isinstance(department, Department) or not department.is_active:
        raise ValidationError("有効な部署を選択してください。")

    prefix = str(department.code)
    Employee = get_user_model()
    numbers = list(
        Employee.objects.filter(employee_number__startswith=prefix).values_list(
            "employee_number", flat=True
        )
    )
    numbers.extend(
        EmployeeNumberHistory.objects.filter(employee_number__startswith=prefix).values_list(
            "employee_number", flat=True
        )
    )
    issued = [
        int(number[1:])
        for number in numbers
        if re.fullmatch(rf"{prefix}[0-9]{{4}}", number or "")
    ]
    serial = max(issued, default=0) + 1
    if serial > 9999:
        raise ValidationError("この部署の社員番号が上限に達しました。")
    return f"{prefix}{serial:04d}"


def issue_employee_number(*, department, employee):
    """発行済み番号を削除不可の履歴に保存する。"""
    EmployeeNumberHistory.objects.create(
        department=department,
        employee=employee,
        employee_number=employee.employee_number,
    )
