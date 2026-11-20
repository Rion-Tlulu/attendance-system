"""勤怠管理画面用の表示フィルター。"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from django import template
from django.utils import timezone
from django.utils.dateparse import parse_datetime

register = template.Library()

JST = ZoneInfo("Asia/Tokyo")


@register.filter
def jst_datetime(value):
    """日時を日本時間で読みやすく表示する。"""

    if value is None or value == "":
        return "未記録"

    if isinstance(value, str):
        parsed = parse_datetime(value)

        if parsed is None:
            return value

        value = parsed

    if not isinstance(value, datetime):
        return str(value)

    if timezone.is_naive(value):
        value = timezone.make_aware(
            value,
            JST,
        )

    local_value = timezone.localtime(
        value,
        JST,
    )

    return local_value.strftime("%Y/%m/%d %H:%M")


@register.filter
def plain_label(bound_field):
    """画面設計に合わせ、ラベル末尾の「:」を付けずに label タグを出力する。"""

    return bound_field.label_tag(label_suffix="")


@register.filter
def dt_parts(value):
    """「YYYY/MM/DD HH:MM」形式の表示文字列を日付と時刻に分ける（確認画面の大きな時刻表示用）。"""

    text = "" if value is None else str(value)
    match = re.fullmatch(r"(\d{4}/\d{2}/\d{2}) (\d{1,2}:\d{2}(?::\d{2})?)", text)
    if match is None:
        return {"date": "", "time": text}
    return {"date": match.group(1), "time": match.group(2)}


def _short(text, work_day):
    """表示用の「YYYY/MM/DD HH:MM」を、勤務日と同じ日付なら時刻だけにする。"""
    parts = dt_parts(text)
    if not parts["date"]:
        return parts["time"]
    day_text = work_day.strftime("%Y/%m/%d") if hasattr(work_day, "strftime") else str(work_day or "")
    if parts["date"] == day_text:
        return parts["time"]
    year, month, day = parts["date"].split("/")
    return f"{int(month)}/{int(day)} {parts['time']}"


@register.filter
def short_dt(value, work_day):
    """確認画面用：勤務日と同じ日付なら「HH:MM」、別の日なら「M/D HH:MM」で表示する。"""
    return _short(value, work_day)


@register.filter
def break_pairs(current_breaks, proposal_breaks):
    """修正前・修正後の休憩を順番どおりに対応づけ、[{number, before, after, changed}] を返す。

    値は表示用の {"start": ..., "end": ...} のまま受け取り、比較は表示文字列で行う。
    """
    current_breaks = list(current_breaks or [])
    proposal_breaks = list(proposal_breaks or [])
    rows = []
    for index in range(max(len(current_breaks), len(proposal_breaks))):
        before = current_breaks[index] if index < len(current_breaks) else None
        after = proposal_breaks[index] if index < len(proposal_breaks) else None
        key = lambda item: (item.get("start"), item.get("end")) if item else None  # noqa: E731
        rows.append({
            "number": index + 1,
            "before": before,
            "after": after,
            "changed": key(before) != key(after),
        })
    return rows


@register.filter
def raw_break_pairs(current_breaks, proposal_breaks):
    """保存形式の休憩（started_at / ended_at）を表示用に変換してから break_pairs で対応づける。"""

    def display(items):
        def field(item, name):
            return item.get(name) if isinstance(item, dict) else getattr(item, name, None)

        return [
            {"start": jst_datetime(field(item, "started_at")), "end": jst_datetime(field(item, "ended_at"))}
            for item in (items or [])
        ]

    return break_pairs(display(current_breaks), display(proposal_breaks))


@register.filter
def has_value(value):
    """表示用の日時が実際の値か（「設定なし」「未記録」・空でないか）を返す。"""
    return value not in (None, "", "設定なし", "未記録")


def _time_range(start, end, work_day):
    """休憩の開始・終了を「12:00 〜 13:00」の1つの表示にまとめる。"""
    start_text = _short(start, work_day) if has_value(start) else ""
    end_text = _short(end, work_day) if has_value(end) else ""
    if not start_text and not end_text:
        return "未記録"
    return f"{start_text or '未記録'} 〜 {end_text or '未記録'}"


@register.filter
def grouped_comparison(rows, work_day):
    """日別詳細の比較表：「休憩N開始」「休憩N終了」の2行を「休憩N」の1行にまとめる（画面 06）。

    戻り値は [{"label", "original", "effective", "changed"}]。日時は勤務日と同じ日付なら時刻だけにする。
    休憩が1件だけのときは「休憩」と表示する。
    """
    rows = list(rows or [])
    starts = {}
    ends = {}
    for row in rows:
        match = re.fullmatch(r"休憩(\d+)(開始|終了)", row.label)
        if match:
            (starts if match.group(2) == "開始" else ends)[match.group(1)] = row
    break_count = len(set(starts) | set(ends))

    grouped = []
    seen = set()
    for row in rows:
        match = re.fullmatch(r"休憩(\d+)(開始|終了)", row.label)
        if not match:
            original = _short(row.original, work_day)
            effective = _short(row.effective, work_day)
            grouped.append({"label": row.label, "original": original, "effective": effective,
                            "changed": original != effective})
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        start_row, end_row = starts.get(number), ends.get(number)
        original = _time_range(getattr(start_row, "original", None), getattr(end_row, "original", None), work_day)
        effective = _time_range(getattr(start_row, "effective", None), getattr(end_row, "effective", None), work_day)
        grouped.append({
            "label": "休憩" if break_count == 1 else f"休憩{number}",
            "original": original,
            "effective": effective,
            "changed": original != effective,
        })
    return grouped
