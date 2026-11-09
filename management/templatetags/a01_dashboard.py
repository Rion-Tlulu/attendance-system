"""A01 管理者勤怠一覧向けの表示データ。

既存の management/views.py を変更せず、
社員別の月次状況を集計する。
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
    """YYYY-MMを対象月のdateへ変換する。"""

    current = timezone.localdate().replace(day=1)

    if not raw_value:
        return current, ""

    if not re.fullmatch(
        r"\d{4}-(0[1-9]|1[0-2])",
        raw_value,
    ):
        return current, "対象月の形式が正しくありません。"

    try:
        year, month = map(int, raw_value.split("-"))
        return date(year, month, 1), ""

    except ValueError:
        return current, "対象月を確認してください。"


def _next_month(value):
    """翌月1日を返す。"""

    if value.month == 12:
        return date(value.year + 1, 1, 1)

    return date(
        value.year,
        value.month + 1,
        1,
    )


def _employee_month_url(employee, target_month):
    """既存の社員別月次詳細URLを取得する。"""

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
    """検索条件を保持したページ切替URLを生成。"""

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
    """A01の表示情報を取得する。"""

    request = context.get("request")

    # 既存ビューの認可に加え、表示側でも確認する
    if (
        request is None
        or not request.user.is_authenticated
        or not getattr(
            request.user,
            "is_business_admin",
            False,
        )
    ):
        return {"allowed": False}

    target_month, month_error = _month_from_query(request.GET.get("month", ""))

    filters = {
        "month": target_month.strftime("%Y-%m"),
        "q": request.GET.get("q", "").strip()[:100],
        "department": (request.GET.get("department", "").strip()[:100]),
        "status": request.GET.get("status", "all"),
    }

    allowed_statuses = {name for name, _ in STATUS_OPTIONS}

    if filters["status"] not in allowed_statuses:
        filters["status"] = "all"

    Employee = get_user_model()

    # 無効化された社員の過去勤怠も保持・表示する
    employees = list(Employee.objects.all().order_by("employee_number"))

    # 部署の選択肢
    department_names = sorted(
        {str(getattr(employee, "department", "") or "") for employee in employees}
        - {""}
    )

    # 社員番号・氏名検索
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

    # 部署検索
    if filters["department"]:
        employees = [
            employee
            for employee in employees
            if str(getattr(employee, "department", "") or "") == filters["department"]
        ]

    employee_ids = [employee.pk for employee in employees]

    end_month = _next_month(target_month)

    stats = {}
    pending_counts = {}
    finalized_ids = set()

    if employee_ids:

        # 対象月の勤務状態を社員別に集計
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

        stats = {record["employee_id"]: record for record in session_qs}

        # 審査中の修正申請
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
            record["work_session__employee_id"]: record["total"]
            for record in pending_qs
        }

        # 月次確定済み社員
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

        # 重要度が高い状態を優先して表示
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

        # 状態による絞り込み
        selected = filters["status"]

        matches = {
            "all": True,
            "attention": bool(pending or incomplete),
            "pending": bool(pending),
            "incomplete": bool(incomplete),
            "finalized": finalized,
            "unfinalized": not finalized,
        }

        if not matches[selected]:
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

    # 一度に25人ずつ表示
    paginator = Paginator(
        rows,
        25,
    )

    page_obj = paginator.get_page(request.GET.get("page"))

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
