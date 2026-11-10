from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.views.decorators.cache import never_cache

from auditlog.models import AuditLog

from .access import business_admin_required
from .forms import EmploymentInfoForm
from .models import EmploymentInfo

Employee = get_user_model()


def snapshot(record):
    """監査履歴用の変更前後の値"""

    if record is None:
        return {}

    return {
        "department": record.department,
        "hire_date": (record.hire_date.isoformat() if record.hire_date else None),
        "leave_date": (record.leave_date.isoformat() if record.leave_date else None),
    }


@never_cache
@business_admin_required
def employement_edit(request, employee_id):
    """社員の雇用情報を閲覧・編集する"""

    employee = get_object_or_404(
        Employee,
        pk=employee_id,
    )

    if request.method == "POST":
        with transaction.atomic():
            employee = get_object_or_404(
                Employee.objects.select_for_update(),
                pk=employee_id,
            )

            record = (
                EmploymentInfo.objects.select_for_update()
                .filter(employee=employee)
                .first()
            )

            if record is None:
                record = EmploymentInfo(employee=employee)

            before = snapshot(record if record.pk else None)

            form = EmploymentInfoForm(
                request.POST,
                instance=record,
            )

            if form.is_valid():
                updated = form.save(commit=False)
                updated.employee = employee
                updated.save()

                AuditLog.objects.create(
                    actor=request.user,
                    target_employee=employee,
                    action=AuditLog.Action.EMPLOYEE_UPDATE,
                    target_model="EmploymentInfo",
                    target_id=str(updated.pk),
                    before_data=before,
                    after_data=snapshot(updated),
                    reason="社員の雇用情報の更新",
                    details={},
                )

                messages.success(request, "雇用情報を保存しました")

                return redirect(
                    "management:employees",
                )
    else:
        record = EmploymentInfo.objects.filter(employee=employee).first()

        if record is None:
            record = EmploymentInfo(employee=employee)

        form = EmploymentInfoForm(instance=record)

    return render(
        request,
        "management/employment_edit.html",
        {
            "employee": employee,
            "form": form,
        },
    )
