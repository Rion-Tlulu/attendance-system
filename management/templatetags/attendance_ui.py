"""勤怠管理画面用の表示フィルター。"""

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
