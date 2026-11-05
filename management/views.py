from django.shortcuts import render
from django.views.decorators.cache import never_cache

from accounts.decorators import business_admin_required


@never_cache
@business_admin_required
def home(request):
    """管理者用ホーム（Phase 3では仮画面）。"""

    return render(
        request,
        "management/home.html",
    )


import csv
import io
import logging

from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from attendance.forms import MonthSelectForm
from attendance.models import MonthlyClosing
from attendance.reporting import build_monthly_report
from auditlog.models import AuditLog
from corrections.models import CorrectionRequest

from .access import business_admin_required
from .forms import (
    EmployeeCreateForm,
    EmployeeEditForm,
    MonthClosingForm,
    ReviewForm,
)
from .services import (
    AdminActionError,
    finalize_month,
    reopen_month,
    review_correction,
    validate_target_month,
)

logger = logging.getLogger(__name__)
Employee = get_user_model()


def _month_from_url(year, month):
    try:
        return validate_target_month(year, month)
    except AdminActionError as exc:
        raise Http404(str(exc)) from exc


def _requested_month(request):
    """管理者画面の年月をフォームで検証。"""

    if "month" in request.GET:
        form = MonthSelectForm(request.GET)

        if form.is_valid():
            return form, form.cleaned_data["month"]

        return form, None

    month = timezone.localdate().replace(day=1)

    form = MonthSelectForm(initial={"month": month.strftime("%Y-%m")})

    return form, month


def _audit_employee_change(
    *,
    actor,
    employee,
    action,
    before,
    after,
):
    AuditLog.objects.create(
        actor=actor,
        target_employee=employee,
        action=action,
        target_model="Employee",
        target_id=str(employee.pk),
        before_data=before,
        after_data=after,
        reason="管理者による社員情報の登録・変更",
        details={},
    )


def _employee_snapshot(employee):
    """パスワードを含まない監査用の社員情報。"""

    names = [
        "employee_number",
        "first_name",
        "last_name",
        "department",
        "is_active",
        "is_business_admin",
    ]

    data = {}

    for name in names:
        if hasattr(employee, name):
            value = getattr(employee, name)

            if name == "department" and value is not None:
                value = str(value)

            data[name] = value

    return data


# ==========================================
# A01：管理者勤怠一覧
# ==========================================


@never_cache
@business_admin_required
def attendance_list(request):
    """対象社員と対象月の勤怠を検索する。"""

    form, target_month = _requested_month(request)

    if target_month is None:
        return render(
            request,
            "management/attendance_list.html",
            {
                "form": form,
                "entries": [],
                "page_obj": None,
            },
            status=400,
        )

    keyword = request.GET.get("q", "").strip()[:100]

    queryset = Employee.objects.all().order_by("employee_number")

    if keyword:
        queryset = queryset.filter(
            Q(employee_number__icontains=keyword)
            | Q(first_name__icontains=keyword)
            | Q(last_name__icontains=keyword)
        )

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    entries = []

    # ページ内の社員についてのみ集計
    for employee in page_obj.object_list:
        report = build_monthly_report(
            employee,
            target_month,
        )

        entries.append(
            {
                "employee": employee,
                "report": report,
            }
        )

    return render(
        request,
        "management/attendance_list.html",
        {
            "form": form,
            "month_query": target_month.strftime("%Y-%m"),
            "keyword": keyword,
            "entries": entries,
            "page_obj": page_obj,
        },
    )


# ==========================================
# A02：管理者修正申請一覧
# ==========================================


@never_cache
@business_admin_required
def correction_queue(request):
    """修正申請を状態別に一覧表示する。"""

    status_filter = request.GET.get("status", "pending")

    allowed = {
        "all",
        "pending",
        "approved",
        "returned",
        "withdrawn",
    }

    if status_filter not in allowed:
        status_filter = "pending"

    queryset = CorrectionRequest.objects.select_related(
        "requested_by", "work_session"
    ).order_by("-created_at", "-pk")

    if status_filter != "all":
        queryset = queryset.filter(status=status_filter)

    page_obj = Paginator(queryset, 20).get_page(request.GET.get("page"))

    return render(
        request,
        "management/correction_queue.html",
        {
            "page_obj": page_obj,
            "status_filter": status_filter,
        },
    )


# ==========================================
# A03：修正申請詳細・承認・差戻し
# ==========================================


@never_cache
@business_admin_required
def correction_review_detail(request, pk):
    """管理者用の申請詳細画面。"""

    correction = get_object_or_404(
        CorrectionRequest.objects.select_related(
            "requested_by",
            "work_session",
        ),
        pk=pk,
    )

    can_review = (
        correction.status == CorrectionRequest.Status.PENDING
        and correction.requested_by_id != request.user.pk
    )

    return render(
        request,
        "management/correction_review.html",
        {
            "correction": correction,
            "can_review": can_review,
            "form": ReviewForm(),
        },
    )


@never_cache
@business_admin_required
@require_POST
def correction_review_submit(request, pk):
    """申請を承認または差し戻す。"""

    form = ReviewForm(request.POST)

    if not form.is_valid():
        messages.error(
            request,
            "審査内容を確認してください。",
        )
        return redirect(
            "management:correction_detail",
            pk=pk,
        )

    try:
        review_correction(
            manager_id=request.user.pk,
            correction_id=pk,
            action=form.cleaned_data["action"],
            return_reason=(form.cleaned_data["return_reason"]),
        )

    except (
        AdminActionError,
        CorrectionRequest.DoesNotExist,
    ) as exc:
        messages.error(request, str(exc))

    except Exception:
        logger.exception(
            "修正申請の審査に失敗: correction_id=%s",
            pk,
        )
        messages.error(
            request,
            "審査を完了できませんでした。" "管理担当者へ確認してください。",
        )

    else:
        messages.success(
            request,
            "修正申請を処理しました。",
        )

    return redirect(
        "management:correction_detail",
        pk=pk,
    )


# ==========================================
# A04：社員一覧・登録・編集
# ==========================================


@never_cache
@business_admin_required
def employee_list(request):
    """社員アカウントを検索する。"""

    keyword = request.GET.get("q", "").strip()[:100]

    queryset = Employee.objects.all().order_by("employee_number")

    if keyword:
        queryset = queryset.filter(
            Q(employee_number__icontains=keyword)
            | Q(first_name__icontains=keyword)
            | Q(last_name__icontains=keyword)
        )

    page_obj = Paginator(queryset, 20).get_page(request.GET.get("page"))

    return render(
        request,
        "management/employee_list.html",
        {
            "page_obj": page_obj,
            "keyword": keyword,
        },
    )


@never_cache
@business_admin_required
def employee_create(request):
    """一般社員の新規登録。"""

    if request.method == "POST":
        form = EmployeeCreateForm(request.POST)

        if form.is_valid():
            with transaction.atomic():
                employee = form.save(commit=False)

                employee.set_password(form.cleaned_data["temporary_password"])

                employee.is_active = True
                employee.is_business_admin = False
                employee.is_staff = False
                employee.is_superuser = False

                if hasattr(employee, "must_change_password"):
                    employee.must_change_password = True

                employee.save()

                _audit_employee_change(
                    actor=request.user,
                    employee=employee,
                    action=AuditLog.Action.EMPLOYEE_CREATE,
                    before={},
                    after=_employee_snapshot(employee),
                )

            messages.success(
                request,
                "一般社員を登録しました。",
            )
            return redirect("management:employees")

    else:
        form = EmployeeCreateForm()

    return render(
        request,
        "management/employee_form.html",
        {
            "form": form,
            "creating": True,
        },
    )


@never_cache
@business_admin_required
def employee_edit(request, employee_id):
    """社員の基本情報を変更する。"""

    employee = get_object_or_404(
        Employee,
        pk=employee_id,
    )

    if request.method == "POST":
        form = EmployeeEditForm(
            request.POST,
            instance=employee,
        )

        if form.is_valid():
            wants_active = form.cleaned_data["is_active"]

            if employee.pk == request.user.pk and not wants_active:
                form.add_error(
                    "is_active",
                    "自分自身を利用停止にはできません。",
                )

            elif (
                employee.is_business_admin
                and not request.user.is_superuser
                and not wants_active
            ):
                form.add_error(
                    "is_active",
                    "業務管理者の利用停止は" "上位管理者による確認が必要です。",
                )

            else:
                with transaction.atomic():
                    employee = Employee.objects.select_for_update().get(pk=employee_id)

                    before = _employee_snapshot(employee)

                    # ロック取得後も対象を確認
                    if not form.cleaned_data["is_active"] and (
                        employee.pk == request.user.pk
                        or (
                            employee.is_business_admin and not request.user.is_superuser
                        )
                    ):
                        form.add_error(
                            "is_active",
                            "この社員の利用停止はできません。",
                        )

                    else:
                        for field_name in EmployeeEditForm.Meta.fields:
                            setattr(
                                employee,
                                field_name,
                                form.cleaned_data[field_name],
                            )

                        employee.save()
                        updated = employee

                        _audit_employee_change(
                            actor=request.user,
                            employee=updated,
                            action=AuditLog.Action.EMPLOYEE_UPDATE,
                            before=before,
                            after=_employee_snapshot(updated),
                        )

                if not form.errors:
                    messages.success(request, "社員情報を更新しました")

                    return redirect("management:employees")

    else:
        form = EmployeeEditForm(instance=employee)

    return render(
        request,
        "management/employee_form.html",
        {
            "form": form,
            "creating": False,
            "employee": employee,
        },
    )


# 社員の月次勤怠詳細
@never_cache
@business_admin_required
def employee_month(request, employee_id, year, month):
    """指定社員の月次勤怠を確認する"""

    employee = get_object_or_404(
        Employee,
        pk=employee_id,
    )

    target_month = _month_from_url(year, month)

    report = build_monthly_report(
        employee,
        target_month,
    )

    no_record_count = sum(row.record_key == "no_record" for row in report.rows)

    page_obj = Paginator(report.rows, 7).get_page(request.GET.get("page"))

    return render(
        request,
        "management/employee_month.html",
        {
            "employee": employee,
            "report": report,
            "page_obj": page_obj,
            "no_record_count": no_record_count,
            "closing_form": MonthClosingForm(),
        },
    )


# 月次確定・確定解除
@never_cache
@business_admin_required
@require_POST
def month_finalize(request, employee_id, year, month):
    """社員の月次勤怠を確定する"""

    target_month = _month_from_url(year, month)

    form = MonthClosingForm(request.POST)

    if not form.is_valid():
        messages.error(
            request,
            "記録なしの日の照合確認をしてください",
        )

    else:
        try:
            finalize_month(
                manager_id=request.user.pk,
                employee_id=employee_id,
                target_month=target_month,
                checked_no_record=(form.cleaned_data["checked_no_record"]),
            )

        except (AdminActionError, Employee.DoesNotExist) as exc:
            messages.error(request, str(exc))

        else:
            messages.success(
                request,
                "月次勤怠を確定しました",
            )

    return redirect(
        "management:employee_month",
        employee_id=employee_id,
        year=year,
        month=month,
    )


@never_cache
@business_admin_required
@require_POST
def month_reopen(request, employee_id, year, month):
    """確定済みの月次勤怠を解除する"""

    target_month = _month_from_url(year, month)

    try:
        reopen_month(
            manager_id=request.user.pk,
            employee_id=employee_id,
            target_month=target_month,
            reason=request.POST.get("reason", ""),
        )

    except (AdminActionError, Employee.DoesNotExist) as exc:
        messages.error(request, str(exc))

    else:
        messages.success(
            request,
            "月次勤怠の確定を解除しました",
        )

    return redirect(
        "management:employee_month",
        employee_id=employee_id,
        year=year,
        month=month,
    )


# 確定済みCSV出力
def _csv_safe(value):
    """表計算ソフトでの数式解釈を防ぐ"""

    if value is None:
        return ""

    text = str(value)

    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text

    if text.startswith(("\t", "\r", "\n")):
        return "'" + text

    return text


@never_cache
@business_admin_required
@require_POST
@transaction.atomic
def month_csv(request, employee_id, year, month):
    """確定済みの月次勤怠をCSV出力する"""

    employee = get_object_or_404(
        Employee.objects.select_for_update(),
        pk=employee_id,
    )

    target_month = _month_from_url(year, month)

    closing = (
        MonthlyClosing.objects.select_for_update()
        .filter(
            employee=employee,
            target_month=target_month,
        )
        .first()
    )

    finalized = bool(closing and closing.status == MonthlyClosing.Status.FINALIZED)

    if not finalized:
        messages.error(
            request,
            "確定済みの月だけCSV出力できます",
        )

        return redirect(
            "management:employee_month",
            employee_id=employee_id,
            year=year,
            month=month,
        )
    report = build_monthly_report(
        employee,
        target_month,
    )

    output = io.StringIO(newline="")

    writer = csv.writer(
        output,
        lineterminator="\r\n",
    )

    writer.writerow(
        [
            "社員番号",
            "氏名",
            "勤務日",
            "出勤",
            "退勤",
            "休憩秒数",
            "実働秒数",
            "休憩時間",
            "記録状態",
            "修正状態",
            "確定状態",
        ]
    )

    name = employee.get_full_name()

    # CSVは日付順
    for row in reversed(report.rows):
        writer.writerow(
            [
                _csv_safe(employee.employee_number),
                _csv_safe(name),
                row.day.isoformat(),
                row.clock_in,
                row.clock_out,
                row.break_seconds if row.break_seconds is not None else "",
                row.work_seconds if row.work_seconds is not None else "",
                row.break_display,
                row.work_display,
                row.record_label,
                row.correction_label,
                row.closing_label,
            ]
        )

    csv_text = "\ufeff" + output.getvalue()

    response = HttpResponse(
        csv_text,
        content_type="text/csv; charset=utf-8",
    )

    safe_employee_number = "".join(
        char if char.isascii() and (char.isalnum() or char in "-_") else "_"
        for char in str(employee.employee_number)
    )[:50]

    response["Content-Disposition"] = (
        "attachment; "
        f'filename="attendance_{safe_employee_number}_'
        f'{year:04d}{month:02d}.csv"'
    )

    response["Cache-Control"] = "no-store"

    # CSV出力操作を監査ログに記録
    AuditLog.objects.create(
        actor=request.user,
        target_employee=employee,
        action=AuditLog.Action.CSV_EXPORT,
        target_model="MonthlyClosing",
        target_id=(f"{employee.pk}:" f"{target_month.isoformat()}"),
        before_data={},
        after_data={
            "exported": True,
            "target_month": target_month.isoformat(),
        },
        reason="確定済み勤怠データのCSV出力",
        details={
            "target_month": target_month.isoformat(),
            "row_count": len(report.rows),
        },
    )

    return response


# 監査履歴一覧
@never_cache
@business_admin_required
def audit_history(request):
    """操作履歴を新しい順に表示する"""
    queryset = AuditLog.objects.all().order_by("-pk")

    action = request.GET.get("action", "").strip()

    if action:
        valid_actions = {value for value, _ in AuditLog.Action.choices}

        if action in valid_actions:
            queryset = queryset.filter(action=action)
        else:
            action = ""

    page_obj = Paginator(queryset, 30).get_page(request.GET.get("page"))

    return render(
        request,
        "management/audit_history.html",
        {
            "page_obj": page_obj,
            "selected_action": action,
            "actions": AuditLog.Action.choices,
        },
    )


@never_cache
@business_admin_required
def audit_detail(request, pk):
    """操作履歴の詳細を閲覧する"""

    item = get_object_or_404(
        AuditLog,
        pk=pk,
    )

    return render(
        request,
        "management/audit_detail.html",
        {"item": item},
    )
