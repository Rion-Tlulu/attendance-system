"""業務管理者権限の付与・取消画面。"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from .access import business_admin_required
from .forms import BusinessAdminRoleForm
from .role_management import RoleChangeError, change_business_admin_role


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
                return redirect("management:employee_edit", employee_id=employee.pk)
        employee.refresh_from_db()
    else:
        role = "admin" if employee.is_business_admin else "employee"
        form = BusinessAdminRoleForm(initial={
            "expected_role": role, "desired_role": role,
        })

    return render(request, "management/employee_role.html", {
        "employee": employee, "form": form,
    })
