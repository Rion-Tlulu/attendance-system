from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import (
    get_object_or_404,
    render,
)
from django.views.decorators.cache import never_cache

from auditlog.models import AuditLog
from config.db_errors import SAVE_FAILURE_ERRORS, UNCONFIRMED_SAVE_MESSAGE, log_save_failure
from attendance.models import WorkSession
from corrections.models import CorrectionRequest

from .access import business_admin_required
from .forms import EmploymentInfoForm
from .models import EmploymentInfo
from .navigation import return_to_list

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
        try:
            with transaction.atomic():
                actor = Employee.objects.select_for_update().get(pk=request.user.pk)
                if not actor.is_active or not actor.is_business_admin:
                    raise PermissionDenied("この管理機能を利用する権限がありません。")
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
                    record = EmploymentInfo(employee=employee, department=employee.department)

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
                    employee.hire_date = updated.hire_date
                    employee.retirement_date = updated.leave_date
                    employee.save(update_fields=["hire_date", "retirement_date"])

                    AuditLog.objects.create(
                        actor=actor,
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

                    return return_to_list(request, "a03", "management:employees")
        except SAVE_FAILURE_ERRORS:
            # ロールバック済み。保存結果を確認できない旨を示し、入力値を保持して再表示する。
            log_save_failure("employment_edit", employee_id=employee_id)
            employee = get_object_or_404(Employee, pk=employee_id)
            record = EmploymentInfo.objects.filter(employee=employee).first() or EmploymentInfo(
                employee=employee, department=employee.department,
            )
            form = EmploymentInfoForm(request.POST, instance=record)
            form.is_valid()
            form.add_error(None, UNCONFIRMED_SAVE_MESSAGE)
    else:
        record = EmploymentInfo.objects.filter(employee=employee).first()

        if record is None:
            record = EmploymentInfo(employee=employee, department=employee.department)

        form = EmploymentInfoForm(instance=record)

    return render(
        request,
        "management/employment_edit.html",
        {
            "employee": employee,
            "form": form,
        },
    )
