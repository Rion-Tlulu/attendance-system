"""Frozen values used by finalized month views and CSV handoff."""

from .models import WorkSession
from .validation import employment_dates, is_employed_on


def build_closing_snapshot(employee, target_month, report, closing):
    hire_date, leave_date = employment_dates(employee)
    profile = getattr(employee, "employement_info", None)
    department = profile.department if profile else employee.department
    sessions = {
        item.work_date: item for item in WorkSession.objects.filter(
            employee=employee,
            work_date__year=target_month.year,
            work_date__month=target_month.month,
        )
    }
    daily = []
    for row in sorted(report.rows, key=lambda item: item.day):
        if not is_employed_on(employee, row.day):
            continue
        session = sessions.get(row.day)
        daily.append({
            "day": row.day.isoformat(),
            "clock_in_at": session.clock_in_at.isoformat() if session and session.clock_in_at else None,
            "clock_out_at": session.clock_out_at.isoformat() if session and session.clock_out_at else None,
            "break_seconds": row.break_seconds,
            "work_seconds": row.work_seconds,
            "record_state": row.record_label,
            "session_version": session.version if session else None,
        })
    return {
        "employee_number": employee.employee_number,
        "name": employee.get_full_name(),
        "department": department or "",
        "target_month": target_month.strftime("%Y-%m"),
        "hire_date": hire_date.isoformat() if hire_date else None,
        "leave_date": leave_date.isoformat() if leave_date else None,
        "daily": daily,
        "recorded_days": sum(row["work_seconds"] is not None for row in daily),
        "work_seconds": sum(row["work_seconds"] or 0 for row in daily),
        "break_seconds": sum(row["break_seconds"] or 0 for row in daily),
        "incomplete_count": 0,
        "finalized_at": closing.finalized_at.isoformat(),
        "data_version": closing.version,
    }
