"""A01 管理者勤怠一覧の表示データ。

既存の社員検索、部署検索、状態検索、
月次集計、ページネーションを維持する。

F11: 日別未完了件数グラフを追加する。
"""

import re
from datetime import date
from urllib.parse import urlencode

from django import template
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from attendance.chart_data import (
    build_incomplete_count_chart,
)
from attendance.models import MonthlyClosing, WorkSession
from corrections.models import CorrectionRequest

register = template.Library()


STATUS_OPTIONS = (
    ("all", "すべて"),
    ("attention", "確認が必要"),
    ("pending", "修正申請の審査待ち"),
    ("incomplete", "未完了の勤務あり"),
    ("finalized", "月次確定済み"),
    ("unfinalized", "月次未確定"),
)


def _month_from_query(raw_value):
    """対象月の取得と形式検証。"""

    current = timezone.localdate().replace(day=1)

    if not raw_value:
        return current, ""

    if not re.fullmatch(
        r"[0-9]{4}-(0[1-9]|1[0-2])",
        raw_value,
    ):
        return current, "対象月の形式が正しくありません。"

    try:
        year, month = map(
            int,
            raw_value.split("-"),
        )

        return date(year, month, 1), ""

    except ValueError:
        return current, "対象月を確認してください。"


def _next_month(value):
    """翌月1日を返す。"""

    if value.month == 12:
        return date(value.year + 1, 1, 1)

    return date(value.year, value.month + 1, 1)


def _employee_month_url(employee, target_month):
    """社員別月次詳細URLを返す。"""

    kwargs = {
        "employee_id": employee.pk,
        "year": target_month.year,
        "month": target_month.month,
    }

    try:
        return reverse(
            "management:employee_month",
            kwargs=kwargs,
        )

    except NoReverseMatch:
        try:
            return reverse(
                "management:employee_month",
                args=[
                    employee.pk,
                    target_month.year,
                    target_month.month,
                ],
            )

        except NoReverseMatch:
            return ""


def _query_for_page(filters, page_number):
    """検索条件を引き継いだページURLを作成。"""

    params = {
        "month": filters["month"],
        "page": page_number,
    }

    for name in ("q", "department", "status"):
        value = filters[name]

        if value and value != "all":
            params[name] = value

    return urlencode(params)


@register.simple_tag(takes_context=True)
def a01_snapshot(context):
    """管理者の勤怠一覧とグラフを集計する。"""

    request = context.get("request")

    # ------------------------------------------
    # 権限
    # ------------------------------------------

    if (
        request is None
        or not request.user.is_authenticated
        or not request.user.is_active
        or not getattr(
            request.user,
            "is_business_admin",
            False,
        )
    ):
        return {"allowed": False}

    # ------------------------------------------
    # 対象月・フィルター
    # ------------------------------------------

    target_month, month_error = _month_from_query(request.GET.get("month", ""))

    filters = {
        "month": target_month.strftime("%Y-%m"),
        "q": request.GET.get("q", "").strip()[:100],
        "department": request.GET.get("department", "").strip()[:100],
        "status": request.GET.get("status", "all"),
    }

    allowed_statuses = {name for name, _ in STATUS_OPTIONS}

    if filters["status"] not in allowed_statuses:
        filters["status"] = "all"

    # ------------------------------------------
    # 社員一覧
    # ------------------------------------------

    Employee = get_user_model()

    employees = list(Employee.objects.all().order_by("employee_number"))

    department_names = sorted(
        {
            str(
                getattr(
                    employee,
                    "department",
                    "",
                )
                or ""
            )
            for employee in employees
        }
        - {""}
    )

    # ------------------------------------------
    # 社員番号・氏名検索
    # ------------------------------------------

    q = filters["q"].casefold()

    if q:
        employees = [
            employee
            for employee in employees
            if q
            in (
                f"{employee.employee_number} "
                f"{employee.first_name} "
                f"{employee.last_name} "
                f"{employee.last_name} "
                f"{employee.first_name}"
            ).casefold()
        ]

    # ------------------------------------------
    # 部署検索
    # ------------------------------------------

    if filters["department"]:
        employees = [
            employee
            for employee in employees
            if str(
                getattr(
                    employee,
                    "department",
                    "",
                )
                or ""
            )
            == filters["department"]
        ]

    employee_ids = [item.pk for item in employees]

    end_month = _next_month(target_month)

    # ------------------------------------------
    # 勤怠・申請・月次確定の集計
    # ------------------------------------------

    stats = {}
    pending_counts = {}
    finalized_ids = set()

    if employee_ids:

        session_qs = (
            WorkSession.objects.filter(
                employee_id__in=employee_ids,
                work_date__gte=target_month,
                work_date__lt=end_month,
            )
            .values("employee_id")
            .annotate(
                records=Count("pk"),
                completed=Count(
                    "pk",
                    filter=Q(status=WorkSession.Status.COMPLETED),
                ),
                incomplete=Count(
                    "pk",
                    filter=Q(
                        status__in=(
                            WorkSession.Status.WORKING,
                            WorkSession.Status.ON_BREAK,
                        )
                    ),
                ),
            )
        )

        stats = {item["employee_id"]: item for item in session_qs}

        pending_qs = (
            CorrectionRequest.objects.filter(
                work_session__employee_id__in=employee_ids,
                work_session__work_date__gte=target_month,
                work_session__work_date__lt=end_month,
                status=CorrectionRequest.Status.PENDING,
            )
            .values("work_session__employee_id")
            .annotate(total=Count("pk"))
        )

        pending_counts = {
            item["work_session__employee_id"]: item["total"] for item in pending_qs
        }

        finalized_ids = set(
            MonthlyClosing.objects.filter(
                employee_id__in=employee_ids,
                target_month=target_month,
                status=MonthlyClosing.Status.FINALIZED,
            ).values_list(
                "employee_id",
                flat=True,
            )
        )

    # ------------------------------------------
    # 社員別の一覧行
    # ------------------------------------------

    rows = []

    for employee in employees:
        employee_stats = stats.get(
            employee.pk,
            {},
        )

        completed = employee_stats.get("completed", 0)

        incomplete = employee_stats.get("incomplete", 0)

        pending = pending_counts.get(employee.pk, 0)

        records = employee_stats.get("records", 0)

        finalized = employee.pk in finalized_ids

        if pending:
            label = "審査待ちあり"
            tone = "warning"

        elif incomplete:
            label = "未完了あり"
            tone = "danger"

        elif finalized:
            label = "確定済み"
            tone = "success"

        elif completed:
            label = "記録あり"
            tone = "info"

        else:
            label = "記録なし"
            tone = "neutral"

        matches = {
            "all": True,
            "attention": bool(pending or incomplete),
            "pending": bool(pending),
            "incomplete": bool(incomplete),
            "finalized": finalized,
            "unfinalized": not finalized,
        }

        if not matches[filters["status"]]:
            continue

        rows.append(
            {
                "employee": employee,
                "department": str(
                    getattr(
                        employee,
                        "department",
                        "",
                    )
                    or "未設定"
                ),
                "completed": completed,
                "incomplete": incomplete,
                "pending": pending,
                "records": records,
                "finalized": finalized,
                "status_label": label,
                "tone": tone,
                "detail_url": _employee_month_url(
                    employee,
                    target_month,
                ),
            }
        )

    # ------------------------------------------
    # F11: グラフ用データ
    # ------------------------------------------

    # ページネーション前の検索結果を使用。
    selected_employee_ids = [row["employee"].pk for row in rows]

    incomplete_chart = build_incomplete_count_chart(
        target_month,
        selected_employee_ids,
        dom_id="f11-a01",
    )

    # ------------------------------------------
    # ページネーション
    # ------------------------------------------

    paginator = Paginator(rows, 25)

    page_obj = paginator.get_page(request.GET.get("page"))

    # ------------------------------------------
    # テンプレートへの戻り値
    # ------------------------------------------

    return {
        "allowed": True,
        "filters": filters,
        "month_error": month_error,
        "target_month": target_month,
        "departments": department_names,
        "status_options": STATUS_OPTIONS,
        "page_obj": page_obj,
        "employee_count": len(rows),
        "pending_count": sum(row["pending"] for row in rows),
        "incomplete_count": sum(row["incomplete"] for row in rows),
        "finalized_count": sum(1 for row in rows if row["finalized"]),
        "incomplete_chart": incomplete_chart,
        "previous_query": (
            _query_for_page(
                filters,
                page_obj.previous_page_number(),
            )
            if page_obj.has_previous()
            else ""
        ),
        "next_query": (
            _query_for_page(
                filters,
                page_obj.next_page_number(),
            )
            if page_obj.has_next()
            else ""
        ),
    }
