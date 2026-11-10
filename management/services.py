import calendar

from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from attendance.models import (
    BreakInterval,
    MonthlyClosing,
    WorkSession,
)
from attendance.reporting import build_monthly_report
from auditlog.models import AuditLog
from corrections.models import CorrectionRequest
from corrections.services import (
    CorrectionError,
    current_values,
    validate_proposal,
)

from notifications.services import notify_correction_reviewed


class AdminActionError(Exception):
    """管理者操作で業務ルールを満たさない場合。"""


def _manager(manager_id):
    """操作管理者の権限をDB上で再確認する。"""

    Employee = get_user_model()

    manager = Employee.objects.get(pk=manager_id)

    if not manager.is_active or not manager.is_business_admin:
        raise AdminActionError("この操作を行う管理者権限がありません。")

    return manager


def _employee_locked(employee_id):
    """対象社員の行を取得する。"""

    Employee = get_user_model()

    return Employee.objects.select_for_update().get(pk=employee_id)


def _audit(
    *,
    actor,
    employee,
    action,
    model,
    record_id,
    before,
    after,
    reason,
    details=None,
):
    AuditLog.objects.create(
        actor=actor,
        target_employee=employee,
        action=action,
        target_model=model,
        target_id=str(record_id),
        before_data=before,
        after_data=after,
        reason=reason,
        details=details or {},
    )


def _as_datetime(value):
    if value is None:
        return None

    parsed = parse_datetime(value)

    if parsed is None or timezone.is_naive(parsed):
        raise AdminActionError("修正案の日時形式が不正です。")

    return parsed


def _set_reviewer(correction, manager):
    """審査担当者フィールドが存在する場合に記録。"""

    names = {field.name for field in CorrectionRequest._meta.fields}

    if "reviewed_by" in names:
        correction.reviewed_by = manager

    elif "reviewer" in names:
        correction.reviewer = manager


# ==========================================
# 修正申請の承認・差戻し
# ==========================================


@transaction.atomic
def review_correction(
    *,
    manager_id,
    correction_id,
    action,
    return_reason="",
):
    """審査中申請を承認または差し戻す。"""

    if action not in ("approve", "return"):
        raise AdminActionError("審査操作が不正です。")

    manager = _manager(manager_id)

    # 最初に対象社員IDを取得
    reference = CorrectionRequest.objects.select_related("work_session").get(
        pk=correction_id
    )

    target_id = reference.work_session.employee_id

    if manager.pk == target_id:
        raise AdminActionError("自分自身の修正申請は審査できません。")

    # Phase 7と同じく対象社員を先にロック
    employee = _employee_locked(target_id)

    session = WorkSession.objects.select_for_update().get(pk=reference.work_session_id)

    correction = CorrectionRequest.objects.select_for_update().get(pk=correction_id)

    if correction.status != CorrectionRequest.Status.PENDING:
        raise AdminActionError("審査中の申請だけ処理できます。")

    if correction.requested_by_id != employee.pk:
        raise AdminActionError("申請者と勤務対象者が一致しません。")

    if MonthlyClosing.objects.filter(
        employee=employee,
        target_month=session.work_date.replace(day=1),
        status=MonthlyClosing.Status.FINALIZED,
    ).exists():
        raise AdminActionError("確定済みの勤務月は変更できません。")

    if session.version != correction.original_version:
        raise AdminActionError(
            "申請後に勤務記録が変更されています。" "内容を確認し直してください。"
        )

    before = {
        "status": session.status,
        "version": session.version,
        "effective_values": current_values(session),
    }

    reason = return_reason.strip()

    if action == "return":
        if not 1 <= len(reason) <= 500:
            raise AdminActionError("差戻し理由は1〜500文字で入力してください。")

        correction.status = CorrectionRequest.Status.RETURNED
        correction.return_reason = reason

        audit_action = AuditLog.Action.CORRECTION_RETURN

    else:
        # 申請時とは別に、承認時にも再検証
        try:
            proposal = validate_proposal(
                correction.proposal,
                session.work_date,
            )
        except CorrectionError as exc:
            raise AdminActionError(str(exc)) from exc

        start = _as_datetime(proposal["clock_in_at"])
        end = _as_datetime(proposal["clock_out_at"])
        breaks = proposal["breaks"]

        if start is None:
            new_status = WorkSession.Status.NO_RECORD

        elif end is None:
            new_status = WorkSession.Status.WORKING

        else:
            new_status = WorkSession.Status.COMPLETED

        # 別の進行中勤務がある場合に
        # 新たな進行中勤務を作らない
        if new_status == WorkSession.Status.WORKING:
            already_active = (
                WorkSession.objects.filter(
                    employee=employee,
                    status__in=[
                        WorkSession.Status.WORKING,
                        WorkSession.Status.ON_BREAK,
                    ],
                )
                .exclude(pk=session.pk)
                .exists()
            )

            if already_active:
                raise AdminActionError("別の進行中勤務があるため承認できません。")

        # 有効な勤務だけを更新する
        session.clock_in_at = start
        session.clock_out_at = end
        session.status = new_status
        session.version += 1
        session.save()

        # 有効な休憩を再構築する
        # 原打刻ClockEventは変更しない
        BreakInterval.objects.filter(work_session=session).delete()

        for item in breaks:
            BreakInterval.objects.create(
                work_session=session,
                started_at=_as_datetime(item["started_at"]),
                ended_at=_as_datetime(item["ended_at"]),
            )

        correction.status = CorrectionRequest.Status.APPROVED
        correction.return_reason = ""

        audit_action = AuditLog.Action.CORRECTION_APPROVE
        reason = correction.reason

    correction.reviewed_at = timezone.now()
    _set_reviewer(correction, manager)
    correction.save()

    after = {
        "review_status": correction.status,
        "status": session.status,
        "version": session.version,
        "effective_values": current_values(session),
    }

    _audit(
        actor=manager,
        employee=employee,
        action=audit_action,
        model="CorrectionRequest",
        record_id=correction.pk,
        before=before,
        after=after,
        reason=reason,
        details={
            "work_date": session.work_date.isoformat(),
            "correction_id": correction.pk,
        },
    )

    notify_correction_reviewed(correction)

    return correction


# ==========================================
# 月次確定の共通検証
# ==========================================


def validate_target_month(year, month):
    try:
        target = date(year, month, 1)
    except ValueError as exc:
        raise AdminActionError("対象年月が不正です。") from exc

    return target


def _month_has_finished(target_month):
    last_day = calendar.monthrange(
        target_month.year,
        target_month.month,
    )[1]

    return target_month.replace(day=last_day) < timezone.localdate()


def _open_closing_status():
    """既存モデルに定義された未確定状態を選ぶ。"""

    for name in (
        "OPEN",
        "UNFINALIZED",
        "NOT_FINALIZED",
        "REOPENED",
        "DRAFT",
    ):
        value = getattr(
            MonthlyClosing.Status,
            name,
            None,
        )

        if value is not None:
            return value

    raise AdminActionError(
        "月次確定解除用の状態がモデルにありません。"
        "MonthlyClosing.Statusを確認してください。"
    )


# ==========================================
# 月次確定
# ==========================================


@transaction.atomic
def finalize_month(
    *,
    manager_id,
    employee_id,
    target_month,
    checked_no_record,
):
    """対象社員の月次勤怠を確定する。"""

    manager = _manager(manager_id)

    if manager.pk == employee_id:
        raise AdminActionError("自分自身の月次勤怠は確定できません。")

    if not _month_has_finished(target_month):
        raise AdminActionError("対象月の終了後に確定してください。")

    if not checked_no_record:
        raise AdminActionError("記録なしの日の照合確認が必要です。")

    employee = _employee_locked(employee_id)

    # 勤務レコードをロック
    list(
        WorkSession.objects.select_for_update()
        .filter(
            employee=employee,
            work_date__year=target_month.year,
            work_date__month=target_month.month,
        )
        .values_list("pk", flat=True)
    )

    closing = (
        MonthlyClosing.objects.select_for_update()
        .filter(
            employee=employee,
            target_month=target_month,
        )
        .first()
    )

    if closing is not None and closing.status == MonthlyClosing.Status.FINALIZED:
        raise AdminActionError("この月はすでに確定済みです。")

    report = build_monthly_report(
        employee,
        target_month,
    )

    if report.incomplete_count:
        raise AdminActionError("未完了の勤務があるため確定できません。")

    if report.pending_count:
        raise AdminActionError("審査中の修正申請があるため確定できません。")

    no_record_count = sum(row.record_key == "no_record" for row in report.rows)

    before_status = closing.status if closing else "未作成"

    if closing is None:
        closing = MonthlyClosing.objects.create(
            employee=employee,
            target_month=target_month,
            status=MonthlyClosing.Status.FINALIZED,
            finalized_by=manager,
            finalized_at=timezone.now(),
        )

    else:
        closing.status = MonthlyClosing.Status.FINALIZED
        closing.finalized_by = manager
        closing.finalized_at = timezone.now()
        closing.save()

    _audit(
        actor=manager,
        employee=employee,
        action=AuditLog.Action.MONTH_FINALIZE,
        model="MonthlyClosing",
        record_id=closing.pk,
        before={"status": before_status},
        after={
            "status": closing.status,
            "work_seconds": report.total_work_seconds,
            "break_seconds": report.total_break_seconds,
        },
        reason="記録なしの日を別途照合して月次確定",
        details={
            "target_month": target_month.isoformat(),
            "no_record_count": no_record_count,
            "checked_no_record": True,
        },
    )

    return closing


# ==========================================
# 月次確定解除
# ==========================================


@transaction.atomic
def reopen_month(
    *,
    manager_id,
    employee_id,
    target_month,
    reason,
):
    """確定済み月を未確定へ戻す。"""

    manager = _manager(manager_id)

    if manager.pk == employee_id:
        raise AdminActionError("自分自身の月次確定は解除できません。")

    reason = reason.strip()

    if not 1 <= len(reason) <= 500:
        raise AdminActionError("確定解除理由は1〜500文字で入力してください。")

    employee = _employee_locked(employee_id)

    closing = (
        MonthlyClosing.objects.select_for_update()
        .filter(
            employee=employee,
            target_month=target_month,
        )
        .first()
    )

    if closing is None or closing.status != MonthlyClosing.Status.FINALIZED:
        raise AdminActionError("対象の月は確定済みではありません。")

    previous_status = closing.status
    open_status = _open_closing_status()

    closing.status = open_status
    closing.finalized_by = None
    closing.finalized_at = None
    closing.save()

    _audit(
        actor=manager,
        employee=employee,
        action=AuditLog.Action.MONTH_REOPEN,
        model="MonthlyClosing",
        record_id=closing.pk,
        before={"status": previous_status},
        after={"status": open_status},
        reason=reason,
        details={
            "target_month": target_month.isoformat(),
        },
    )

    return closing
