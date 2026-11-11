"""A03 社員管理画面の表示データ。"""

from urllib.parse import urlencode

from django import template
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db.models import Q
from django.urls import reverse

from management.models import EmploymentInfo

register = template.Library()


def _page_query(filters, page):
    """検索条件を保持したページ切替URL。"""

    values = {"page": page}

    for name in ("q", "department", "status", "role"):
        value = filters.get(name, "")

        if value and value != "all":
            values[name] = value

    return urlencode(values)


def _employee_row(employee):
    """社員1人分の表示情報。"""

    try:
        info = employee.employement_info
    except ObjectDoesNotExist:
        info = None

    department = "未登録"
    hire_date = None
    leave_date = None

    if info is not None:
        department = info.department or "未設定"
        hire_date = info.hire_date
        leave_date = info.leave_date

    return {
        "employee": employee,
        "department": department,
        "hire_date": hire_date,
        "leave_date": leave_date,
        "is_manager": bool(employee.is_business_admin),
        "is_active": bool(employee.is_active),
        "edit_url": reverse(
            "management:employee_edit",
            args=[employee.pk],
        ),
        "employment_url": reverse(
            "management:employment_edit",
            args=[employee.pk],
        ),
    }


@register.simple_tag(takes_context=True)
def a03_directory(context):
    """管理者向け社員一覧のデータを取得する。"""

    request = context.get("request")
    user = getattr(request, "user", None)

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
        return {"allowed": False}

    filters = {
        "q": (request.GET.get("q", "").strip()[:100]),
        "department": (request.GET.get("department", "").strip()[:100]),
        "status": (request.GET.get("status", "all")),
        "role": (request.GET.get("role", "all")),
    }

    if filters["status"] not in (
        "all",
        "active",
        "inactive",
    ):
        filters["status"] = "all"

    if filters["role"] not in (
        "all",
        "employee",
        "business_admin",
    ):
        filters["role"] = "all"

    Employee = get_user_model()

    # 無効化された社員も保持して一覧に含める。
    queryset = Employee.objects.select_related("employement_info").order_by(
        "employee_number"
    )

    # 社員番号・氏名検索
    if filters["q"]:
        for word in filters["q"].split():
            queryset = queryset.filter(
                Q(employee_number__icontains=word)
                | Q(first_name__icontains=word)
                | Q(last_name__icontains=word)
            )

    # 部署検索
    if filters["department"]:
        queryset = queryset.filter(employement_info__department=(filters["department"]))

    # 利用状態検索
    if filters["status"] == "active":
        queryset = queryset.filter(is_active=True)

    elif filters["status"] == "inactive":
        queryset = queryset.filter(is_active=False)

    # 業務管理者検索
    if filters["role"] == "business_admin":
        queryset = queryset.filter(is_business_admin=True)

    elif filters["role"] == "employee":
        queryset = queryset.filter(is_business_admin=False)

    total_count = queryset.count()
    active_count = queryset.filter(is_active=True).count()

    inactive_count = queryset.filter(is_active=False).count()

    manager_count = queryset.filter(is_business_admin=True, is_active=True).count()

    # 既存の在籍情報から部署選択肢を取得。
    departments = list(
        EmploymentInfo.objects.exclude(department="")
        .order_by("department")
        .values_list(
            "department",
            flat=True,
        )
        .distinct()
    )

    paginator = Paginator(
        queryset,
        25,
    )

    page_obj = paginator.get_page(request.GET.get("page"))

    rows = [_employee_row(employee) for employee in page_obj.object_list]

    previous_query = ""
    next_query = ""

    if page_obj.has_previous():
        previous_query = _page_query(
            filters,
            page_obj.previous_page_number(),
        )

    if page_obj.has_next():
        next_query = _page_query(
            filters,
            page_obj.next_page_number(),
        )

    return {
        "allowed": True,
        "filters": filters,
        "departments": departments,
        "rows": rows,
        "page_obj": page_obj,
        "total_count": total_count,
        "active_count": active_count,
        "inactive_count": inactive_count,
        "manager_count": manager_count,
        "previous_query": previous_query,
        "next_query": next_query,
    }
