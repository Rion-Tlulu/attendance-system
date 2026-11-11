import calendar

from dataclasses import dataclass, replace
from datetime import date, datetime

from django.db.models import Prefetch
from django.utils import timezone

from .models import (
    BreakInterval,
    ClockEvent,
    MonthlyClosing,
    WorkSession,
)
from corrections.models import CorrectionRequest

WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")


# ----------------------------------------
# 表示の共通処理
# ----------------------------------------


def format_duration(seconds):
    """秒を○時間○分に変換する。"""
    minutes = int(seconds) // 60
    hours, remainder = divmod(minutes, 60)
    return f"{hours}時間{remainder:02d}分"


def format_day(day):
    """日付を10/27（火）の形式にする。"""
    return f"{day.month}/{day.day}" f"（{WEEKDAYS[day.weekday()]}）"


def format_datetime(value):
    """日時を日本時間の文字列に変換する。"""
    if value is None:
        return "未記録"

    return timezone.localtime(value).strftime("%Y/%m/%d %H:%M")


def format_clock(value, work_day):
    """日付またぎの場合は月日も表示する。"""
    if value is None:
        return "—"

    local = timezone.localtime(value)

    if local.date() != work_day:
        return local.strftime("%m/%d %H:%M")

    return local.strftime("%H:%M")


# ----------------------------------------
# 勤務時間計算
# ----------------------------------------


@dataclass
class DurationResult:
    complete: bool
    work_seconds: int | None = None
    break_seconds: int | None = None


def calculate_duration(session, breaks):
    """実働・休憩時間を秒単位で計算する。"""

    if session is None:
        return DurationResult(False)

    if session.status != WorkSession.Status.COMPLETED:
        return DurationResult(False)

    start = session.clock_in_at
    end = session.clock_out_at

    if start is None or end is None or end < start:
        return DurationResult(False)

    # 勤務日が出勤した日の日本日付であること
    if timezone.localtime(start).date() != session.work_date:
        return DurationResult(False)

    total_break = 0
    previous_end = start

    for item in sorted(
        breaks,
        key=lambda value: value.started_at,
    ):
        if item.ended_at is None:
            return DurationResult(False)

        if item.started_at < previous_end:
            return DurationResult(False)

        if item.ended_at <= item.started_at:
            return DurationResult(False)

        if item.ended_at > end:
            return DurationResult(False)

        total_break += int((item.ended_at - item.started_at).total_seconds())

        previous_end = item.ended_at

    work_seconds = int((end - start).total_seconds()) - total_break

    if work_seconds < 0:
        return DurationResult(False)

    return DurationResult(
        complete=True,
        work_seconds=work_seconds,
        break_seconds=total_break,
    )


def get_breaks(session):
    """勤務に関連する休憩を取得する。"""
    if session is None:
        return []

    if hasattr(session, "report_breaks"):
        return session.report_breaks

    return list(session.break_intervals.order_by("started_at", "pk"))


def get_corrections(session, employee=None, work_day=None):
    """勤務に関連する申請履歴を取得する。"""
    if employee is not None and work_day is not None:
        return list(CorrectionRequest.objects.filter(
            employee=employee, work_date=work_day,
        ).order_by("-created_at", "-pk"))
    if session is None:
        return []

    if hasattr(session, "report_corrections"):
        return session.report_corrections

    return list(session.correction_requests.order_by("-created_at", "-pk"))


def get_work_queryset(employee):
    """本人の勤務と関連情報をまとめて取得する。"""

    return WorkSession.objects.filter(employee=employee).prefetch_related(
        Prefetch(
            "break_intervals",
            queryset=BreakInterval.objects.order_by("started_at", "pk"),
            to_attr="report_breaks",
        ),
        Prefetch(
            "correction_requests",
            queryset=CorrectionRequest.objects.order_by("-created_at", "-pk"),
            to_attr="report_corrections",
        ),
    )


# ----------------------------------------
# 日別の表示情報
# ----------------------------------------


@dataclass
class DailyRow:
    day: date
    day_label: str

    clock_in: str
    clock_out: str
    work_display: str
    break_display: str

    work_seconds: int | None
    break_seconds: int | None

    record_key: str
    record_label: str

    correction_key: str
    correction_label: str

    closing_key: str
    closing_label: str

    has_pending: bool


def build_daily_row(day, session, is_finalized=False, corrections=None):
    """1日分の勤怠表示データを生成する。"""

    breaks = get_breaks(session)
    corrections = get_corrections(session) if corrections is None else corrections

    duration = calculate_duration(session, breaks)

    if session is None:
        no_record = True
    else:
        no_record = (
            session.status == WorkSession.Status.NO_RECORD
            and session.clock_in_at is None
            and session.clock_out_at is None
            and not breaks
        )

    if no_record:
        record_key = "no_record"
        record_label = "記録なし"

    elif duration.complete:
        record_key = "recorded"
        record_label = "記録済み"

    else:
        record_key = "incomplete"
        record_label = "未完了"

    latest = corrections[0] if corrections else None

    if latest:
        correction_key = latest.status
        correction_label = latest.get_status_display()
    else:
        correction_key = "none"
        correction_label = "なし"

    has_pending = any(
        item.status == CorrectionRequest.Status.PENDING for item in corrections
    )

    if duration.complete:
        work_display = format_duration(duration.work_seconds)
        break_display = format_duration(duration.break_seconds)
    else:
        work_display = "—"
        break_display = "—"

    return DailyRow(
        day=day,
        day_label=format_day(day),
        clock_in=(format_clock(session.clock_in_at, day) if session else "—"),
        clock_out=(format_clock(session.clock_out_at, day) if session else "—"),
        work_display=work_display,
        break_display=break_display,
        work_seconds=(duration.work_seconds if duration.complete else None),
        break_seconds=(duration.break_seconds if duration.complete else None),
        record_key=record_key,
        record_label=record_label,
        correction_key=correction_key,
        correction_label=correction_label,
        closing_key=("finalized" if is_finalized else "open"),
        closing_label=("確定済み" if is_finalized else "未確定"),
        has_pending=has_pending,
    )


# ----------------------------------------
# 月次集計
# ----------------------------------------


@dataclass
class MonthlyReport:
    month: date
    month_label: str
    month_query: str

    rows: list[DailyRow]

    total_work_seconds: int
    total_break_seconds: int

    work_display: str
    break_display: str

    incomplete_count: int
    pending_count: int

    is_finalized: bool
    closing_label: str

    previous_month: str | None
    next_month: str | None


def adjacent_month(month, offset):
    """前月・翌月をYYYY-MMで返す。"""

    index = month.year * 12 + month.month - 1 + offset

    year, zero_month = divmod(index, 12)

    if not 1 <= year <= 9999:
        return None

    return f"{year:04d}-{zero_month + 1:02d}"


def build_monthly_report(employee, target_month):
    """対象月全体の勤怠集計を作成する。"""

    first_day = target_month.replace(day=1)

    last_day_number = calendar.monthrange(
        first_day.year,
        first_day.month,
    )[1]

    last_day = first_day.replace(day=last_day_number)

    sessions = get_work_queryset(employee).filter(
        work_date__range=(first_day, last_day)
    )

    session_map = {session.work_date: session for session in sessions}
    correction_map = {}
    for correction in CorrectionRequest.objects.filter(
        employee=employee, work_date__range=(first_day, last_day),
    ).order_by("-created_at", "-pk"):
        correction_map.setdefault(correction.work_date, []).append(correction)

    closing = MonthlyClosing.objects.filter(
        employee=employee,
        target_month=first_day,
    ).first()

    is_finalized = bool(closing and closing.status == MonthlyClosing.Status.FINALIZED)

    rows = []
    total_work_seconds = 0
    total_break_seconds = 0
    incomplete_count = 0
    pending_count = 0

    # 新しい日付から表示
    for number in range(last_day_number, 0, -1):
        day = first_day.replace(day=number)

        row = build_daily_row(
            day,
            session_map.get(day),
            is_finalized,
            corrections=correction_map.get(day, []),
        )

        rows.append(row)

        if row.record_key == "recorded":
            total_work_seconds += row.work_seconds
            total_break_seconds += row.break_seconds

        elif row.record_key == "incomplete":
            incomplete_count += 1

        if row.has_pending:
            pending_count += 1

    # 完了勤務0件の場合も、月次集計の値は0
    # 記録なしの日別表示とは区別する
    report = MonthlyReport(
        month=first_day,
        month_label=(f"{first_day.year}年{first_day.month}月"),
        month_query=first_day.strftime("%Y-%m"),
        rows=rows,
        total_work_seconds=total_work_seconds,
        total_break_seconds=total_break_seconds,
        work_display=format_duration(total_work_seconds),
        break_display=format_duration(total_break_seconds),
        incomplete_count=incomplete_count,
        pending_count=pending_count,
        is_finalized=is_finalized,
        closing_label=("確定済み" if is_finalized else "未確定"),
        previous_month=adjacent_month(first_day, -1),
        next_month=adjacent_month(first_day, 1),
    )
    if is_finalized and closing.snapshot:
        frozen = closing.snapshot
        by_day = {item["day"]: item for item in frozen["daily"]}
        frozen_rows = []
        for row in report.rows:
            data = by_day.get(row.day.isoformat())
            if data is None:
                continue
            clock_in = datetime.fromisoformat(data["clock_in_at"]) if data["clock_in_at"] else None
            clock_out = datetime.fromisoformat(data["clock_out_at"]) if data["clock_out_at"] else None
            work_seconds = data["work_seconds"]
            break_seconds = data["break_seconds"]
            frozen_rows.append(replace(
                row,
                clock_in=format_clock(clock_in, row.day),
                clock_out=format_clock(clock_out, row.day),
                work_seconds=work_seconds,
                break_seconds=break_seconds,
                work_display=format_duration(work_seconds) if work_seconds is not None else "—",
                break_display=format_duration(break_seconds) if break_seconds is not None else "—",
                record_key="recorded" if work_seconds is not None else "no_record",
                record_label=data["record_state"],
            ))
        report.rows = frozen_rows
        report.total_work_seconds = frozen["work_seconds"]
        report.total_break_seconds = frozen["break_seconds"]
        report.work_display = format_duration(frozen["work_seconds"])
        report.break_display = format_duration(frozen["break_seconds"])
        report.incomplete_count = frozen["incomplete_count"]
        report.pending_count = 0
    return report


def get_daily_session(employee, work_day):
    """本人の指定日の勤務を取得する。"""

    return get_work_queryset(employee).filter(work_date=work_day).first()


# ----------------------------------------
# 原打刻と現在の有効値
# ----------------------------------------


@dataclass
class ComparisonRow:
    label: str
    original: str
    effective: str


def build_comparison_rows(session, breaks, events):
    """原打刻と現在の有効値を比較する。"""

    raw_in = []
    raw_out = []
    raw_break_starts = []
    raw_break_ends = []

    for event in events:
        if event.kind == ClockEvent.Kind.CLOCK_IN:
            raw_in.append(event.recorded_at)

        elif event.kind == ClockEvent.Kind.CLOCK_OUT:
            raw_out.append(event.recorded_at)

        elif event.kind == ClockEvent.Kind.BREAK_START:
            raw_break_starts.append(event.recorded_at)

        elif event.kind == ClockEvent.Kind.BREAK_END:
            raw_break_ends.append(event.recorded_at)

    def first(items):
        return items[0] if items else None

    rows = [
        ComparisonRow(
            label="出勤",
            original=format_datetime(first(raw_in)),
            effective=format_datetime(session.clock_in_at if session else None),
        ),
    ]

    count = max(
        len(raw_break_starts),
        len(raw_break_ends),
        len(breaks),
    )

    for index in range(count):
        current = breaks[index] if index < len(breaks) else None

        raw_start = raw_break_starts[index] if index < len(raw_break_starts) else None
        raw_end = raw_break_ends[index] if index < len(raw_break_ends) else None

        rows.append(
            ComparisonRow(
                f"休憩{index + 1}開始",
                format_datetime(raw_start),
                format_datetime(current.started_at if current else None),
            )
        )

        rows.append(
            ComparisonRow(
                f"休憩{index + 1}終了",
                format_datetime(raw_end),
                format_datetime(current.ended_at if current else None),
            )
        )

    rows.append(
        ComparisonRow(
            label="退勤",
            original=format_datetime(first(raw_out)),
            effective=format_datetime(session.clock_out_at if session else None),
        )
    )

    return rows
