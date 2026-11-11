"""Shared checks for the effective working interval and employment dates."""

import calendar

from .models import WorkSession


def employment_dates(employee):
    profile = getattr(employee, "employement_info", None)
    # 雇用情報がある場合はその空欄も確定値として扱う。退職日の解除後に
    # 旧アカウント側の値が復活しないようにする。
    hire_date = profile.hire_date if profile else employee.hire_date
    leave_date = profile.leave_date if profile else employee.retirement_date
    return hire_date, leave_date


def is_employed_on(employee, work_day):
    hire_date, leave_date = employment_dates(employee)
    # Pre-migration accounts may not yet have a verified hire date. New accounts
    # require one; retain their existing records until an administrator fills it.
    return bool((hire_date is None or hire_date <= work_day) and (leave_date is None or work_day <= leave_date))


def employed_during_month(employee, target_month):
    hire_date, leave_date = employment_dates(employee)
    last_day = target_month.replace(day=calendar.monthrange(target_month.year, target_month.month)[1])
    return bool((hire_date is None or hire_date <= last_day)
                and (leave_date is None or leave_date >= target_month))


def overlapping_sessions(employee, start, end, *, exclude_session_id=None):
    """Compare only the proposed interval with other effective intervals.

    A zero-length interval has no overlap. An open interval extends indefinitely.
    Existing unrelated bad records must not prevent a local correction.
    """
    if start is None or (end is not None and end <= start):
        return []
    sessions = WorkSession.objects.filter(
        employee=employee,
        clock_in_at__isnull=False,
    ).exclude(status=WorkSession.Status.NO_RECORD)
    if exclude_session_id is not None:
        sessions = sessions.exclude(pk=exclude_session_id)
    conflicts = []
    for other in sessions:
        other_start, other_end = other.clock_in_at, other.clock_out_at
        if other_end is not None and other_end <= other_start:
            continue
        if (other_end is None or start < other_end) and (end is None or other_start < end):
            conflicts.append(other)
    return conflicts


def month_integrity_issues(employee, target_month):
    """Find every invalid effective session belonging to the target month."""
    issues = []
    sessions = WorkSession.objects.filter(
        employee=employee,
        work_date__year=target_month.year,
        work_date__month=target_month.month,
    ).exclude(status=WorkSession.Status.NO_RECORD).prefetch_related("break_intervals")
    for session in sessions:
        if not is_employed_on(employee, session.work_date):
            issues.append((session.work_date, "在籍期間外"))
        start, end = session.clock_in_at, session.clock_out_at
        if start is None or (end is not None and end < start):
            issues.append((session.work_date, "出退勤の日時"))
            continue
        if overlapping_sessions(employee, start, end, exclude_session_id=session.pk):
            issues.append((session.work_date, "他の勤務との時間重複"))
        if end is None:
            issues.append((session.work_date, "退勤未記録"))
            continue
        previous_end = start
        for interval in sorted(session.break_intervals.all(), key=lambda item: item.started_at):
            if (interval.started_at < previous_end or interval.ended_at is None
                    or interval.ended_at <= interval.started_at or interval.ended_at > end):
                issues.append((session.work_date, "休憩の日時"))
                break
            previous_end = interval.ended_at
    return issues
