"""業務管理者権限の付与・取消画面。"""

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache

from .access import business_admin_required
from .forms import BusinessAdminRoleForm
from .role_management import RoleChangeError, change_business_admin_role
from .navigation import remember_list_query, return_to_list


@never_cache
@business_admin_required
def role_list(request):
    Employee = get_user_model()
    employees = Employee.objects.filter(is_staff=False, is_superuser=False).order_by(
        "employee_number"
    )
    active_manager_count = employees.filter(is_active=True, is_business_admin=True).count()
    keyword = request.GET.get("q", "").strip()[:100]
    status = request.GET.get("status", "all")
    role = request.GET.get("role", "all")
    for word in keyword.split():
        employees = employees.filter(Q(employee_number__icontains=word) | Q(last_name__icontains=word) | Q(first_name__icontains=word))
    if status in ("active", "inactive"):
        employees = employees.filter(is_active=status == "active")
    else:
        status = "all"
    if role in ("admin", "employee"):
        employees = employees.filter(is_business_admin=role == "admin")
    else:
        role = "all"
    remember_list_query(request, "a06", ("q", "status", "role"))
    page_obj = Paginator(employees, 25).get_page(request.GET.get("page"))
    return render(request, "management/role_list.html", {
        "employees": page_obj, "page_obj": page_obj,
        "keyword": keyword, "status_filter": status, "role_filter": role,
        "filter_query": urlencode({"q": keyword, "status": status, "role": role}),
        "active_manager_count": active_manager_count,
    })


@never_cache
@business_admin_required
def employee_role(request, employee_id):
    Employee = get_user_model()
    employee = get_object_or_404(Employee, pk=employee_id)

    if request.method == "POST":
        form = BusinessAdminRoleForm(request.POST)
        if form.is_valid():
            try:
                change_business_admin_role(
                    actor_id=request.user.pk, employee_id=employee.pk,
                    grant=form.cleaned_data["desired_role"] == "admin",
                    expected_role=form.cleaned_data["expected_role"] == "admin",
                    reason=form.cleaned_data["change_reason"],
                )
            except RoleChangeError as exc:
                form.add_error(None, str(exc))
            except DatabaseError:
                form.add_error(None, "同時更新のため変更できませんでした。画面を再読み込みしてお試しください。")
            else:
                messages.success(request, "業務管理者権限を変更しました。")
                return return_to_list(request, "a06", "management:role_list")
        employee.refresh_from_db()
    else:
        role = "admin" if employee.is_business_admin else "employee"
        form = BusinessAdminRoleForm(initial={
            "expected_role": role, "desired_role": role,
        })

    return render(request, "management/employee_role.html", {
        "employee": employee, "form": form,
        "active_manager_count": Employee.objects.filter(is_active=True, is_business_admin=True, is_staff=False, is_superuser=False).count(),
    })
