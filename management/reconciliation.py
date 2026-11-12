"""月次照合画面と確定送信の間のデータ変更を検出する。"""

import hashlib
import json

from django.core import signing

from attendance.models import BreakInterval, MonthlyClosing, WorkSession
from corrections.models import CorrectionRequest
from .models import EmploymentInfo


def _digest(employee, month):
    sessions = list(WorkSession.objects.filter(employee=employee).order_by("pk").values_list(
        "pk", "work_date", "clock_in_at", "clock_out_at", "status", "version", "moved_to_id"
    ))
    session_ids = [row[0] for row in sessions]
    breaks = list(BreakInterval.objects.filter(work_session_id__in=session_ids).order_by("pk").values_list(
        "pk", "work_session_id", "started_at", "ended_at"
    ))
    corrections = list(CorrectionRequest.objects.filter(employee=employee).order_by("pk").values_list(
        "pk", "work_date", "status", "updated_at", "original_version", "proposal"
    ))
    closing = list(MonthlyClosing.objects.filter(employee=employee, target_month=month).values_list(
        "pk", "status", "version"
    ))
    employment = list(EmploymentInfo.objects.filter(employee=employee).values_list(
        "hire_date", "leave_date", "department"
    ))
    payload = [employee.pk, month, employee.hire_date, employee.retirement_date,
               employee.employee_number, employee.department, employment, sessions,
               breaks, corrections, closing]
    data = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def reconciliation_token(employee, month):
    return signing.dumps(
        {"employee": employee.pk, "month": month.isoformat(), "digest": _digest(employee, month)},
        salt="attendance-month-reconciliation-v1",
    )


def reconciliation_matches(employee, month, token):
    try:
        data = signing.loads(token, salt="attendance-month-reconciliation-v1", max_age=3600)
    except (signing.BadSignature, TypeError, ValueError):
        return False
    return data == {
        "employee": employee.pk,
        "month": month.isoformat(),
        "digest": _digest(employee, month),
    }
