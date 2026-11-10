"""F11：勤怠グラフ用テンプレートタグ。

E02：本人の日別実働時間
A04：管理者の社員別日別実働時間

既存ビューの認証・認可を維持しながら、
Chart.js用の表示データを生成する。
"""

import re
from datetime import date

from django import template
from django.contrib.auth import get_user_model
from django.utils import timezone

from attendance.chart_data import (
    build_work_hours_chart,
)

register = template.Library()


def _valid_month(value):
    """YYYY-MM形式の文字列を月初日のdateへ変換する。"""

    if not isinstance(value, str):
        return None

    if not re.fullmatch(
        r"[0-9]{4}-(0[1-9]|1[0-2])",
        value,
    ):
        return None

    try:
        year, month = map(
            int,
            value.split("-"),
        )

        return date(
            year,
            month,
            1,
        )

    except ValueError:
        return None


@register.simple_tag(takes_context=True)
def f11_employee_chart(context):
    """E02：ログイン本人の日別実働グラフ。"""

    request = context.get("request")

    if request is None:
        return None

    user = getattr(
        request,
        "user",
        None,
    )

    if user is None or not user.is_authenticated or not user.is_active:
        return None

    # 対象月の取得
    raw_month = request.GET.get(
        "month",
        "",
    )

    if raw_month:
        target_month = _valid_month(raw_month)

        if target_month is None:
            return None

    else:
        target_month = timezone.localdate().replace(day=1)

    # 本人の勤務だけを集計
    return build_work_hours_chart(
        user,
        target_month,
        dom_id="f11-e02",
    )


@register.simple_tag(takes_context=True)
def f11_manager_chart(context):
    """A04：管理者向け社員別実働グラフ。"""

    request = context.get("request")

    if request is None:
        return None

    user = getattr(
        request,
        "user",
        None,
    )

    # 管理者権限を確認
    if (
        user is None
        or not user.is_authenticated
        or not user.is_active
        or not getattr(
            user,
            "is_business_admin",
            False,
        )
    ):
        return None

    # 現在のURL情報
    match = getattr(
        request,
        "resolver_match",
        None,
    )

    if match is None or match.view_name != "management:employee_month":
        return None

    kwargs = match.kwargs

    employee_id = kwargs.get("employee_id")

    year = kwargs.get("year")

    month = kwargs.get("month")

    # 年月の妥当性を確認
    try:
        target_month = date(
            int(year),
            int(month),
            1,
        )

    except (TypeError, ValueError):
        return None

    # 対象社員を取得
    Employee = get_user_model()

    employee = Employee.objects.filter(pk=employee_id).first()

    if employee is None:
        return None

    # 既存の管理者ビューでもアクセス権を確認すること
    return build_work_hours_chart(
        employee,
        target_month,
        dom_id="f11-a04",
    )
