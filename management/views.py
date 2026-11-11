"""勤怠管理システム 管理者ビュー（v1.4対応）。

旧管理機能を維持し、初期パスワードの自動発行・再発行を追加する。
このファイルのみで認証仕様が完成するわけではない。
"""

import csv
import io
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import (
    business_admin_required as account_business_admin_required,
)
from attendance.forms import MonthSelectForm
from attendance.models import MonthlyClosing, WorkSession
from attendance.reporting import build_monthly_report
from attendance.validation import employed_during_month, month_integrity_issues
from auditlog.models import AuditLog
from corrections.models import CorrectionRequest
from corrections.services import current_values as correction_current_values

from .access import business_admin_required
from .forms import (
    EmployeeCreateForm,
    EmployeeEditForm,
    MonthClosingForm,
    ReviewForm,
)
from .initial_passwords import set_initial_password
from .models import EmploymentInfo
from .csv_format import csv_safe as _csv_safe
from .services import (
    AdminActionError,
    finalize_month,
    reopen_month,
    review_correction,
    validate_target_month,
)


@never_cache
@account_business_admin_required
def home(request):
    """管理者用ホーム（既存の認可方式を維持）。"""
    return render(request, "management/home.html")


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
    reason="管理者による社員情報の登録・変更",
):
    AuditLog.objects.create(
        actor=actor,
        target_employee=employee,
        action=action,
        target_model="Employee",
        target_id=str(employee.pk),
        before_data=before,
        after_data=after,
        reason=reason,
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
        "requested_by", "employee", "work_session"
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
    """修正前後を比較して申請を審査する画面。"""

    correction = get_object_or_404(
        CorrectionRequest.objects.select_related(
            "requested_by",
            "employee",
            "work_session",
        ),
        pk=pk,
    )

    session = correction.work_session or WorkSession.objects.filter(
        employee=correction.employee, work_date=correction.work_date,
    ).first()

    # 現在の有効値
    current_record = correction_current_values(session)

    # 対象月が確定済みか
    target_month = correction.work_date.replace(day=1)

    month_finalized = MonthlyClosing.objects.filter(
        employee_id=correction.employee_id,
        target_month=target_month,
        status=MonthlyClosing.Status.FINALIZED,
    ).exists()

    # 申請時と勤務データ版が一致するか
    version_matches = (
        (session is None and correction.original_version is None) or
        (session is not None and correction.original_version == session.version)
    )

    # 自分自身の申請・勤務は審査不可
    is_self_request = (
        correction.requested_by_id == request.user.pk
        or correction.employee_id == request.user.pk
    )

    # UIで審査ボタンを表示してよいか
    can_review = (
        correction.status == CorrectionRequest.Status.PENDING
        and not is_self_request
        and not month_finalized
        and version_matches
        and (not correction.is_proxy or (
            not correction.employee.is_active
            and correction.requested_by.is_active
            and correction.requested_by.is_business_admin
        ))
    )

    author_valid = correction.requested_by.is_active and correction.requested_by.is_business_admin
    can_proxy_withdraw = (
        correction.is_proxy and correction.status == CorrectionRequest.Status.PENDING
        and (correction.requested_by_id == request.user.pk or not author_valid)
        and request.user.pk != correction.employee_id
    )

    return render(
        request,
        "management/correction_review.html",
        {
            "correction": correction,
            "current_values": current_record,
            "can_review": can_review,
            "month_finalized": month_finalized,
            "version_matches": version_matches,
            "is_self_request": is_self_request,
            "can_proxy_withdraw": can_proxy_withdraw,
            "proxy_author_invalid": not author_valid,
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

    queryset = Employee.objects.select_related("employement_info").order_by(
        "employee_number"
    )

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
    """F07：初期パスワードを安全に自動生成して社員を登録する。"""

    if request.method == "POST":
        form = EmployeeCreateForm(request.POST)
        if form.is_valid():
            password = None
            employee = None
            try:
                with transaction.atomic():
                    employee = form.save(commit=False)
                    password = set_initial_password(employee)
                    employee.is_active = True
                    employee.is_business_admin = False
                    employee.is_staff = False
                    employee.is_superuser = False
                    employee.save()
                    EmploymentInfo.objects.create(
                        employee=employee,
                        hire_date=form.cleaned_data["hire_date"],
                    )

                    _audit_employee_change(
                        actor=request.user,
                        employee=employee,
                        action=AuditLog.Action.EMPLOYEE_CREATE,
                        before={},
                        after=_employee_snapshot(employee),
                    )
            except IntegrityError:
                # 同時に同じ社員番号が登録されたケースも再表示を禁止する。
                form.add_error(
                    "employee_number",
                    "この社員番号はすでに登録されています。",
                )
            else:
                # 成功したPOST応答で1回だけ表示。session/DB/URLへ平文を保存しない。
                response = render(
                    request,
                    "management/employee_created.html",
                    {
                        "employee": employee,
                        "initial_password": password,
                        "expires_at": employee.initial_password_expires_at,
                        "operation_label": "新規社員登録",
                    },
                )
                response["Referrer-Policy"] = "no-referrer"
                response["X-Robots-Tag"] = "noindex, nofollow"
                return response
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

            else:
                try:
                    with transaction.atomic():
                        active_admin_ids = list(
                            Employee.objects.select_for_update().filter(
                                is_active=True, is_business_admin=True,
                            ).order_by("pk").values_list("pk", flat=True)
                        )
                        actor = Employee.objects.select_for_update().get(pk=request.user.pk)
                        if not actor.is_active or not actor.is_business_admin:
                            raise PermissionDenied("この管理機能を利用する権限がありません。")
                        employee = Employee.objects.select_for_update().get(pk=employee_id)

                        before = _employee_snapshot(employee)

                        if not wants_active and employee.pk == request.user.pk:
                            form.add_error("is_active", "自分自身を利用停止にはできません。")
                        elif not wants_active and employee.is_business_admin:
                            if employee.pk in active_admin_ids and len(active_admin_ids) <= 2:
                                form.add_error("is_active", "有効な管理者は2人以上必要です。")
                        elif wants_active and not employee.is_active and CorrectionRequest.objects.filter(
                            employee=employee,
                            is_proxy=True,
                            status=CorrectionRequest.Status.PENDING,
                        ).exists():
                            form.add_error("is_active", "審査中の代理申請を処理または取下げてください。")

                        if not form.errors:
                            for field_name in EmployeeEditForm.Meta.fields:
                                setattr(employee, field_name, form.cleaned_data[field_name])

                            employee.save()
                            updated = employee

                            _audit_employee_change(
                                actor=request.user,
                                employee=updated,
                                action=AuditLog.Action.EMPLOYEE_UPDATE,
                                before=before,
                                after=_employee_snapshot(updated),
                                reason=form.cleaned_data.get("change_reason") or "社員情報の変更",
                            )
                except IntegrityError:
                    form.add_error("employee_number", "この社員番号はすでに登録されています。")

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
            "incomplete_count": employee.work_sessions.filter(
                status__in=["working", "on_break"],
            ).count(),
            "pending_count": CorrectionRequest.objects.filter(
                employee=employee,
                status=CorrectionRequest.Status.PENDING,
            ).count(),
        },
    )


@never_cache
@business_admin_required
@require_http_methods(["GET", "POST"])
def employee_reset_password(request, employee_id):
    """管理者による本人確認済み社員の初期パスワード再発行。"""

    employee = get_object_or_404(Employee, pk=employee_id)

    # 権限者や技術管理者の再発行は、より厳格な別の運用で行う。
    if (
        employee.pk == request.user.pk
        or not employee.is_active
        or employee.is_staff
        or employee.is_superuser
        or employee.is_business_admin
    ):
        return HttpResponseBadRequest(
            "このアカウントは管理画面から再発行できません。"
        )

    if request.method == "GET":
        issued_version = (
            employee.initial_password_issued_at.isoformat()
            if employee.initial_password_issued_at is not None
            else None
        )
        # 署名付き・短時間有効の確認チケット。平文パスワードは含めない。
        ticket = signing.dumps(
            {
                "employee_id": employee.pk,
                "manager_id": request.user.pk,
                "issued_version": issued_version,
            },
            salt="attendance-initial-password-reset-v1",
        )
        return render(
            request,
            "management/employee_reset_confirm.html",
            {"employee": employee, "ticket": ticket},
        )

    if request.POST.get("confirm") != "yes":
        return HttpResponseBadRequest("本人確認と再発行の確認が必要です。")

    try:
        payload = signing.loads(
            request.POST.get("ticket", ""),
            salt="attendance-initial-password-reset-v1",
            max_age=600,
        )
    except signing.BadSignature:
        return HttpResponseBadRequest(
            "確認操作の有効期限が切れています。画面を開き直してください。"
        )

    if not isinstance(payload, dict) or (
        payload.get("employee_id") != employee.pk
        or payload.get("manager_id") != request.user.pk
    ):
        return HttpResponseBadRequest("確認情報が一致しません。")

    with transaction.atomic():
        # PostgreSQLでは行ロックにより同一チケットの重複再発行を防ぐ。
        locked_employee = Employee.objects.select_for_update().get(
            pk=employee.pk
        )
        current_version = (
            locked_employee.initial_password_issued_at.isoformat()
            if locked_employee.initial_password_issued_at is not None
            else None
        )
        if payload.get("issued_version") != current_version:
            return HttpResponseBadRequest(
                "この確認操作は使用済みです。画面を開き直してください。"
            )

        previous_issued_at = locked_employee.initial_password_issued_at
        new_password = set_initial_password(locked_employee)
        # 発行日時を常に新しくし、チケット再利用を無効化する。
        if (
            previous_issued_at is not None
            and locked_employee.initial_password_issued_at <= previous_issued_at
        ):
            locked_employee.initial_password_issued_at = (
                previous_issued_at + timedelta(microseconds=1)
            )
            locked_employee.initial_password_expires_at = (
                locked_employee.initial_password_issued_at
                + timedelta(hours=72)
            )

        locked_employee.save(update_fields=[
            "password",
            "must_change_password",
            "initial_password_issued_at",
            "initial_password_expires_at",
        ])

        # 監査情報に新しい平文やパスワードハッシュは記録しない。
        AuditLog.objects.create(
            actor=request.user,
            target_employee=locked_employee,
            action=AuditLog.Action.EMPLOYEE_UPDATE,
            target_model="Employee",
            target_id=str(locked_employee.pk),
            before_data={"credential_reset": False},
            after_data={"credential_reset": True},
            reason="本人確認後の初期パスワード再発行",
            details={},
        )

    # set_password により以前のログインセッションは次回照合時に失効する。
    response = render(
        request,
        "management/employee_created.html",
        {
            "employee": locked_employee,
            "initial_password": new_password,
            "expires_at": locked_employee.initial_password_expires_at,
            "operation_label": "初期パスワード再発行",
        },
    )
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


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
    closing = MonthlyClosing.objects.filter(employee=employee, target_month=target_month).first()
    frozen_info = closing.snapshot if closing and closing.status == MonthlyClosing.Status.FINALIZED else {}

    # 対象月が終了済みか
    month_is_past = target_month < timezone.localdate().replace(day=1)

    # UI上で確定可能か判定
    # 最終判定は既存のfinalize_month()が行う
    can_finalize = (
        employee.pk != request.user.pk
        and not report.is_finalized
        and month_is_past
        and report.incomplete_count == 0
        and report.pending_count == 0
        and employed_during_month(employee, target_month)
        and not month_integrity_issues(employee, target_month)
    )

    no_record_count = sum(row.record_key == "no_record" for row in report.rows)
    integrity_issues = month_integrity_issues(employee, target_month)

    page_obj = Paginator(report.rows, 7).get_page(request.GET.get("page"))

    return render(
        request,
        "management/employee_month.html",
        {
            "employee": employee,
            "display_employee_number": frozen_info.get("employee_number", employee.employee_number),
            "display_employee_name": frozen_info.get("name", employee.get_full_name()),
            "report": report,
            "page_obj": page_obj,
            "no_record_count": no_record_count,
            "integrity_issues": integrity_issues,
            "closing_form": MonthClosingForm(),
            "month_is_past": month_is_past,
            "can_finalize": can_finalize,
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
            "別管理資料との照合を確認してください",
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
    if month_integrity_issues(employee, target_month):
        messages.error(request, "勤務の不整合を解消して再確定してください。")
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
            "実働時間",
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
