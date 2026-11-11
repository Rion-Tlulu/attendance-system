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
from attendance.models import WorkSession
from corrections.models import CorrectionRequest

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
                dates_changed = (
                    (updated.hire_date.isoformat() if updated.hire_date else None) != before.get("hire_date")
                    or (updated.leave_date.isoformat() if updated.leave_date else None) != before.get("leave_date")
                )
                if dates_changed and CorrectionRequest.objects.filter(
                    employee=employee,
                    status=CorrectionRequest.Status.PENDING,
                ).exists():
                    form.add_error(None, "審査中の申請を処理してから在籍日を変更してください。")

                invalid_work = WorkSession.objects.filter(
                    employee=employee,
                    clock_in_at__isnull=False,
                ).exclude(status=WorkSession.Status.NO_RECORD)
                if updated.hire_date:
                    invalid_work = invalid_work.filter(work_date__lt=updated.hire_date)
                if not invalid_work.exists() and updated.leave_date:
                    invalid_work = WorkSession.objects.filter(
                        employee=employee,
                        clock_in_at__isnull=False,
                        work_date__gt=updated.leave_date,
                    ).exclude(status=WorkSession.Status.NO_RECORD)
                if dates_changed and invalid_work.exists():
                    form.add_error(None, "在籍期間外に有効な勤務が残ります。勤怠を訂正してください。")

                if form.errors:
                    return render(request, "management/employment_edit.html", {
                        "employee": employee, "form": form,
                    })

                updated.save()

                AuditLog.objects.create(
                    actor=request.user,
                    target_employee=employee,
                    action=AuditLog.Action.EMPLOYEE_UPDATE,
                    target_model="EmploymentInfo",
                    target_id=str(updated.pk),
                    before_data=before,
                    after_data=snapshot(updated),
                    reason=form.cleaned_data.get("change_reason") or "社員の雇用情報の更新",
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
