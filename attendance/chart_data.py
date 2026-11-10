"""F11: 勤怠グラフ用の表示データ。

E02: 本人の日別実働時間
A01: 日別未完了勤務件数
A04: 指定社員の日別実働時間

打刻・申請・月次確定・CSVの保存処理は変更しない。
"""

from calendar import monthrange
from collections import defaultdict
from datetime import date

from django.db.models import Count

from attendance.models import BreakInterval, WorkSession
from attendance.reporting import (
    calculate_duration,
    format_duration,
)


def month_bounds(target_month):
    """対象月の初日と翌月初日を返す。"""

    start = target_month.replace(day=1)

    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)

    return start, end


def iter_month_days(target_month):
    """対象月のすべての日付を返す。"""

    start, _ = month_bounds(target_month)
    last_day = monthrange(start.year, start.month)[1]

    for day in range(1, last_day + 1):
        yield date(start.year, start.month, day)


def load_sessions_and_breaks(queryset):
    """対象勤務と休憩をまとめて取得する。"""

    sessions = list(queryset.order_by("work_date", "pk"))

    breaks_by_session = defaultdict(list)

    if not sessions:
        return sessions, breaks_by_session

    session_ids = [item.pk for item in sessions]

    breaks = BreakInterval.objects.filter(work_session_id__in=session_ids).order_by(
        "started_at", "pk"
    )

    for item in breaks:
        breaks_by_session[item.work_session_id].append(item)

    return sessions, breaks_by_session


def work_result(session, breaks):
    """記録状態と実働秒数を返す。"""

    if session is None:
        return "記録なし", None

    if session.status == WorkSession.Status.NO_RECORD:
        return "記録なし", None

    if session.status != WorkSession.Status.COMPLETED:
        return "未完了", None

    duration = calculate_duration(session, breaks)

    if not duration.complete or duration.work_seconds is None:
        return "未完了", None

    seconds = int(duration.work_seconds)

    if seconds < 0:
        return "未完了", None

    return "完了", seconds


def build_work_hours_chart(
    employee,
    target_month,
    *,
    dom_id="f11-work",
):
    """E02/A04: 社員1人の対象月の実働時間。"""

    start, end = month_bounds(target_month)

    queryset = WorkSession.objects.filter(
        employee=employee,
        work_date__gte=start,
        work_date__lt=end,
    )

    sessions, breaks_by_session = load_sessions_and_breaks(queryset)

    sessions_by_date = {item.work_date: item for item in sessions}

    rows = []

    for work_day in iter_month_days(start):
        session = sessions_by_date.get(work_day)

        breaks = breaks_by_session.get(session.pk, []) if session is not None else []

        status, seconds = work_result(
            session,
            breaks,
        )

        rows.append(
            {
                "date": work_day.isoformat(),
                "label": f"{work_day.day}日",
                "status": status,
                "seconds": seconds,
                "value": (seconds / 3600 if seconds is not None else None),
                "display": (format_duration(seconds) if seconds is not None else "—"),
            }
        )

    return {
        "dom_id": dom_id,
        "data_id": f"{dom_id}-data",
        "kind": "work_hours",
        "title": "日別実働時間",
        "month": start.strftime("%Y年%m月"),
        "unit": "時間",
        "value_header": "実働時間",
        "rows": rows,
    }


def build_incomplete_count_chart(
    target_month,
    employee_ids,
    *,
    dom_id="f11-a01",
):
    """A01: 絞り込み済み社員の日別未完了件数。

    ページネーション前の社員IDを受け取る。
    未完了の基準は既存A01と一致させる。
    """

    start, end = month_bounds(target_month)
    counts = defaultdict(int)

    selected_ids = list(dict.fromkeys(employee_ids))

    if selected_ids:
        grouped = (
            WorkSession.objects.filter(
                employee_id__in=selected_ids,
                work_date__gte=start,
                work_date__lt=end,
                status__in=(
                    WorkSession.Status.WORKING,
                    WorkSession.Status.ON_BREAK,
                ),
            )
            .values("work_date")
            .annotate(total=Count("pk"))
            .order_by("work_date")
        )

        for item in grouped:
            counts[item["work_date"]] = item["total"]

    rows = []

    for work_day in iter_month_days(start):
        count = counts[work_day]

        rows.append(
            {
                "date": work_day.isoformat(),
                "label": f"{work_day.day}日",
                "status": "集計済み",
                "seconds": None,
                "value": count,
                "display": f"{count}件",
            }
        )

    return {
        "dom_id": dom_id,
        "data_id": f"{dom_id}-data",
        "kind": "incomplete_count",
        "title": "日別未完了勤務件数",
        "month": start.strftime("%Y年%m月"),
        "unit": "件",
        "value_header": "未完了件数",
        "rows": rows,
    }


def format_seconds(seconds):
    """実働秒数を「○時間○分」形式に変換する。

    Noneは記録なしとして扱い、
    0秒は0時間00分として表示する。
    """

    if seconds is None:
        return "—"

    seconds = int(seconds)

    if seconds < 0:
        raise ValueError("勤務時間に負の秒数は指定できません。")

    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60

    return f"{hours}時間{minutes:02d}分"
