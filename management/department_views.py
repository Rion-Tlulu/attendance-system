import uuid

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, OperationalError, transaction
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_GET

from auditlog.models import AuditLog

from .department_forms import DepartmentForm
from .department_permissions import require_department_manager
from .department_rules import available_department_codes, normalize_department_name
from .models import Department, DepartmentRegistration, EmploymentInfo
from .numbering_ledger import (
    cancel_pending, require_numbering_ready, reserve_pending, sync_after_commit,
)


def _department_data(department):
    return {
        "name": department.name,
        "code": department.code,
        "is_active": department.is_active,
    }


def _registration_matches(previous, posted):
    """操作IDに紐づく登録時の入力内容を比較する。"""
    try:
        name = normalize_department_name(posted.get("name"))
        code = int(posted.get("code", ""))
    except (ValidationError, TypeError, ValueError):
        return False

    active_field = DepartmentForm.base_fields["is_active"]
    active_value = active_field.widget.value_from_datadict(posted, {}, "is_active")
    is_active = active_field.to_python(active_value)
    # 旧履歴には登録時の状態がないため、安全に一致判定できない。
    if previous.is_active is None:
        return False
    return (
        previous.name == name
        and previous.code == code
        and previous.is_active == is_active
    )


def _is_database_contention(error):
    if isinstance(error, IntegrityError):
        return True
    # SQLite のロックと PostgreSQL の直列化失敗・デッドロック・ロック待ち。
    sqlstate = getattr(error, "pgcode", None) or getattr(
        getattr(error, "__cause__", None), "sqlstate", None
    )
    return sqlstate in {"40001", "40P01", "55P03"} or (
        "locked" in str(error).lower() or "busy" in str(error).lower()
    )


@never_cache
def department_list(request):
    require_department_manager(request)

    keyword = request.GET.get("q", "").strip()[:100]
    departments = Department.objects.all().order_by("code")

    if keyword:
        departments = departments.filter(name__icontains=keyword)

    return render(
        request,
        "management/departments/list.html",
        {
            "departments": departments,
            "keyword": keyword,
        },
    )


@never_cache
@require_GET
def department_registration_result(request, operation_id):
    require_department_manager(request)
    registration = get_object_or_404(
        DepartmentRegistration.objects.select_related("department"),
        actor=request.user, operation_id=operation_id,
    )
    return render(request, "management/departments/created.html", {
        "registration": registration,
    })


@never_cache
@require_http_methods(["GET", "POST"])
def department_create(request):
    require_department_manager(request)

    form = DepartmentForm(request.POST or None)

    response_status = 200
    if request.method == "POST":
        operation_raw = request.POST.get("operation_id", "")

        try:
            operation_id = uuid.UUID(operation_raw)
        except (ValueError, TypeError, AttributeError):
            operation_id = None
            form.add_error(None, "操作IDが不正です。画面を再表示してください。")

        if operation_id is not None:
            previous = (
                DepartmentRegistration.objects.filter(
                    actor=request.user,
                    operation_id=operation_id,
                )
                .select_related("department")
                .first()
            )

            if previous:
                if _registration_matches(previous, request.POST):
                    messages.info(request, "この登録操作は既に処理されています。")
                    return redirect("management:department_registration_result",
                                    operation_id=operation_id)
                form.add_error(None, "同じ操作IDで異なる内容は登録できません。")
                response_status = 409

        if operation_id is not None and response_status == 200 and form.is_valid():
            if request.POST.get("preview") == "1":
                try:
                    require_numbering_ready()
                except ValidationError as exc:
                    form.add_error(None, exc)
                    response_status = 503
                else:
                    return render(request, "management/departments/confirm.html", {
                        "department": form.cleaned_data,
                        "operation_id": str(operation_id),
                    })
        if operation_id is not None and response_status == 200 and form.is_valid():
            try:
                with transaction.atomic():
                    actor = get_user_model().objects.select_for_update().get(pk=request.user.pk)
                    if not actor.is_active or not actor.is_business_admin:
                        raise PermissionDenied("部署登録の権限がありません。")
                    require_numbering_ready()
                    code = form.cleaned_data["code"]

                    # フォーム表示後に他の管理者が
                    # コードを登録した場合も再確認する。
                    if code not in available_department_codes():
                        form.add_error("code", "この部署コードは既に使用されています。")
                    else:
                        reserve_pending(
                            kind="department_create", value=code,
                            actor_id=actor.pk, operation_id=operation_id,
                        )
                        department = form.save()

                        DepartmentRegistration.objects.create(
                            department=department,
                            actor=actor,
                            operation_id=operation_id,
                            name=department.name,
                            code=department.code,
                            is_active=department.is_active,
                        )

                        AuditLog.objects.create(
                            actor=actor,
                            action=AuditLog.Action.DEPARTMENT_CREATE,
                            target_model=Department._meta.label,
                            target_id=str(department.pk),
                            before_data={},
                            after_data=_department_data(department),
                            details={"operation_id": str(operation_id)},
                        )
                        sync_after_commit()

            except ValidationError as exc:
                cancel_pending(kind="department_create", operation_id=operation_id)
                form.add_error(None, exc)
                response_status = 503
            except (IntegrityError, OperationalError) as exc:
                cancel_pending(kind="department_create", operation_id=operation_id)
                if not _is_database_contention(exc):
                    raise
                # DB 一意制約、または SQLite の同時書き込みロック。
                if isinstance(exc, IntegrityError):
                    previous = (
                        DepartmentRegistration.objects.filter(
                            actor=request.user, operation_id=operation_id
                        )
                        .select_related("department")
                        .first()
                    )
                    if previous:
                        if _registration_matches(previous, request.POST):
                            messages.info(request, "この登録操作は既に処理されています。")
                            return redirect("management:department_registration_result",
                                            operation_id=operation_id)
                        form.add_error(None, "同じ操作IDで異なる内容は登録できません。")
                        response_status = 409
                if response_status == 200:
                    form.add_error(
                        None, "登録が競合しました。内容を確認して再試行してください。"
                    )
                    response_status = 409
            else:
                if not form.errors:
                    messages.success(request, "部署を登録しました。")
                    return redirect("management:department_registration_result",
                                    operation_id=operation_id)

        # 検証失敗後も同じ操作IDを保持する。
        if operation_id is None:
            operation_id = uuid.uuid4()
    else:
        operation_id = uuid.uuid4()

    stop_reason = ""
    try:
        require_numbering_ready()
    except ValidationError as exc:
        stop_reason = exc.messages[0]

    return render(
        request,
        "management/departments/form.html",
        {
            "form": form,
            "page_title": "部署の新規登録",
            "operation_id": str(operation_id),
            "no_codes": not available_department_codes(),
            "stop_reason": stop_reason,
        },
        status=response_status,
    )


@never_cache
@require_http_methods(["GET", "POST"])
def department_edit(request, pk):
    require_department_manager(request)

    department = get_object_or_404(
        Department,
        pk=pk,
    )
    original_code = department.code

    form = DepartmentForm(
        request.POST or None,
        instance=department,
    )

    if request.method == "POST" and form.is_valid():
        edit_operation_id = None
        try:
            with transaction.atomic():
                actor = get_user_model().objects.select_for_update().get(pk=request.user.pk)
                if not actor.is_active or not actor.is_business_admin:
                    raise PermissionDenied("部署管理の権限がありません。")
                require_numbering_ready()
                current = Department.objects.select_for_update().get(pk=pk)
                if current.code != original_code:
                    form.add_error("code", "部署コードは変更できません。")
                elif (
                    current.name != form.cleaned_data["name"]
                    and (
                        get_user_model().objects.filter(department=current.name).exists()
                        or EmploymentInfo.objects.filter(department=current.name).exists()
                    )
                ):
                    form.add_error("name", "所属社員がいる部署名は変更できません。")
                else:
                    before = _department_data(current)
                    edit_operation_id = uuid.uuid4()
                    reserve_pending(
                        kind="department_edit", value=current.pk,
                        actor_id=actor.pk, operation_id=edit_operation_id,
                    )
                    current.name = form.cleaned_data["name"]
                    current.is_active = form.cleaned_data["is_active"]
                    current.save(update_fields=["name", "is_active"])
                    AuditLog.objects.create(
                        actor=actor,
                        action=AuditLog.Action.DEPARTMENT_UPDATE,
                        target_model=Department._meta.label,
                        target_id=str(current.pk),
                        before_data=before,
                        after_data=_department_data(current),
                        details={"operation_id": str(edit_operation_id)},
                    )
                    sync_after_commit()
        except ValidationError as exc:
            if edit_operation_id is not None:
                cancel_pending(kind="department_edit", operation_id=edit_operation_id)
            form.add_error(None, exc)
        except (IntegrityError, OperationalError) as exc:
            if edit_operation_id is not None:
                cancel_pending(kind="department_edit", operation_id=edit_operation_id)
            if not _is_database_contention(exc):
                raise
            form.add_error(None, "部署情報の更新が競合しました。")
        else:
            if not form.errors:
                messages.success(request, "部署情報を更新しました。")
                return redirect("management:department_list")

    return render(
        request,
        "management/departments/form.html",
        {
            "form": form,
            "department": department,
            "page_title": "部署の編集",
        },
    )
