"""A03 社員管理一覧の表示データ。

既存の社員登録・編集・無効化処理を変更せず、
一覧表示に必要な社員情報を読み取り専用で取得する。
"""

from urllib.parse import urlencode

from django import template
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q
from django.urls import reverse

from management.models import EmploymentInfo

register = template.Library()


def _page_query(filters, page):
    """絞り込み条件を保持したページ切替クエリ。"""

    params = {
        "page": page,
    }

    for name in (
        "q",
        "department",
        "status",
        "role",
    ):
        value = filters.get(name, "")

        if value and value != "all":
            params[name] = value

    return urlencode(params)


def _employee_row(employee):
    """社員1人分の表示データを生成する。"""

    # 現行モデルの関連名は employement_info
    try:
        info = employee.employement_info
    except EmploymentInfo.DoesNotExist:
        info = None

    if info is None:
        department = "未登録"
        hire_date = None
        leave_date = None

    else:
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
        "edit_url": reverse("management:employee_edit", args=[employee.pk]),
        "employment_url": reverse("management:employment_edit", args=[employee.pk]),
    }


@register.simple_tag(takes_context=True)
def a03_directory(context):
    """管理者向け社員管理一覧を取得する。"""

    request = context.get("request")

    if (
        request is None
        or not request.user.is_authenticated
        or not getattr(
            request.user,
            "is_business_admin",
            False,
        )
    ):
        return {
            "allowed": False,
        }

    q = request.GET.get("q", "").strip()[:100]

    department = request.GET.get("department", "").strip()[:100]

    status = request.GET.get("status", "all")
    role = request.GET.get("role", "all")

    if status not in ("all", "active", "inactive"):
        status = "all"

    if role not in (
        "all",
        "business_admin",
        "employee",
    ):
        role = "all"

    filters = {
        "q": q,
        "department": department,
        "status": status,
        "role": role,
    }

    Employee = get_user_model()

    # アカウント無効化後も過去の記録を保持するため、
    # is_active=False の社員も一覧の対象にする。
    queryset = Employee.objects.select_related(
        "employement_info",
    ).order_by("employee_number")

    # 社員番号・氏名の検索
    # 空白区切りで複数の条件を指定できる。
    if q:
        for word in q.split():
            queryset = queryset.filter(
                Q(employee_number__icontains=word)
                | Q(first_name__icontains=word)
                | Q(last_name__icontains=word)
            )

    # 部署
    if department:
        queryset = queryset.filter(employement_info__department=department)

    # 利用状態
    if status == "active":
        queryset = queryset.filter(is_active=True)
    elif status == "inactive":
        queryset = queryset.filter(is_active=False)

    # 業務権限
    # is_staff と is_business_admin を混同しない。
    if role == "business_admin":
        queryset = queryset.filter(is_business_admin=True)
    elif role == "employee":
        queryset = queryset.filter(is_business_admin=False)

    # 件数はページネーション前の検索結果。
    total_count = queryset.count()

    active_count = queryset.filter(is_active=True).count()

    inactive_count = queryset.filter(is_active=False).count()

    manager_count = queryset.filter(is_business_admin=True).count()

    # 登録されている部署の選択肢
    departments = list(
        EmploymentInfo.objects.exclude(department="")
        .order_by("department")
        .values_list("department", flat=True)
        .distinct()
    )

    # 1ページ25人
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
