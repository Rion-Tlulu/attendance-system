from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from attendance.models import (
    BreakInterval,
    MonthlyClosing,
    WorkSession,
)
from attendance.validation import is_employed_on, overlapping_sessions
from corrections.models import CorrectionRequest

from auditlog.models import AuditLog

from notifications.services import notify_correction_submitted


class CorrectionError(Exception):
    """修正申請の業務ルール違反。"""


def _parse_datetime(value):
    if value is None:
        return None

    if not isinstance(value, str):
        raise CorrectionError("日時のデータ形式が不正です。")

    parsed = parse_datetime(value)

    if parsed is None or timezone.is_naive(parsed):
        raise CorrectionError("日時のデータ形式が不正です。")

    return parsed


def _iso(value):
    """秒まで保持した日本時間のISO形式。"""

    if value is None:
        return None

    return timezone.localtime(value).isoformat(timespec="seconds")


def make_proposal(form, break_formset, current=None):
    """検証済みフォームを修正案JSONへ変換する。

    current（current_values の結果）を渡すと、操作が「変更しない」の対象は
    入力欄の値ではなく現在の有効値をそのまま使う（画面 07）。
    """

    current = current or {}
    current_breaks = current.get("breaks") or []
    breaks = []

    for index, entry in enumerate(break_formset.forms):
        data = entry.cleaned_data

        if not data or data.get("DELETE"):
            continue

        if (
            current
            and data.get("op") == "keep"
            and index < len(current_breaks)
        ):
            breaks.append(dict(current_breaks[index]))
            continue

        start = data.get("started_at")
        end = data.get("ended_at")

        if start is None and end is None:
            continue

        breaks.append(
            {
                "started_at": _iso(start),
                "ended_at": _iso(end),
            }
        )

    values = {}

    for name in ("clock_in", "clock_out"):
        field = f"{name}_at"

        if current and form.cleaned_data.get(f"{name}_op") == "keep":
            values[field] = current.get(field)
        else:
            values[field] = _iso(form.cleaned_data[field])

    return {
        "clock_in_at": values["clock_in_at"],
        "clock_out_at": values["clock_out_at"],
        "breaks": breaks,
    }


def validate_proposal(proposal, work_day, now=None):
    """修正案全体の日時と休憩の整合性を検証。"""

    now = now or timezone.now()

    if not isinstance(proposal, dict):
        raise CorrectionError("修正案の形式が不正です。")

    allowed_keys = {
        "clock_in_at",
        "clock_out_at",
        "breaks",
    }

    if set(proposal) != allowed_keys:
        raise CorrectionError("修正案に不正な項目があります。")

    start = _parse_datetime(proposal["clock_in_at"])
    end = _parse_datetime(proposal["clock_out_at"])

    if end is not None and start is None:
        raise CorrectionError("退勤を設定するには出勤日時が必要です。")

    if start is not None and end is not None:
        if end < start:
            raise CorrectionError("退勤日時は出勤日時以降にしてください。")

    breaks = proposal["breaks"]

    if not isinstance(breaks, list) or len(breaks) > 20:
        raise CorrectionError("休憩の登録件数が不正です。")

    normalized_breaks = []

    for item in breaks:
        if not isinstance(item, dict) or set(item) != {"started_at", "ended_at"}:
            raise CorrectionError("休憩情報の形式が不正です。")

        break_start = _parse_datetime(item["started_at"])
        break_end = _parse_datetime(item["ended_at"])

        if break_start is None or break_end is None:
            raise CorrectionError("休憩の開始・終了は両方必要です。")

        if start is None:
            raise CorrectionError("休憩の登録には出勤日時が必要です。")

        if break_end <= break_start:
            raise CorrectionError("休憩終了は開始より後にしてください。")

        normalized_breaks.append((break_start, break_end))

    # 時間の早い順に整理して検証
    normalized_breaks.sort(key=lambda item: item[0])

    previous_end = start

    for break_start, break_end in normalized_breaks:
        if break_start < previous_end:
            raise CorrectionError("休憩時間が重複しています。")

        if end is not None and break_end > end:
            raise CorrectionError("休憩は退勤日時以前にしてください。")

        previous_end = break_end

    all_times = [
        start,
        end,
    ]

    for break_start, break_end in normalized_breaks:
        all_times.extend([break_start, break_end])

    if any(value is not None and value > now for value in all_times):
        raise CorrectionError("未来の日時は申請できません。")

    return {
        "clock_in_at": _iso(start),
        "clock_out_at": _iso(end),
        "breaks": [
            {
                "started_at": _iso(break_start),
                "ended_at": _iso(break_end),
            }
            for break_start, break_end in normalized_breaks
        ],
    }


def proposal_work_day(proposal, original_day):
    start = _parse_datetime(proposal["clock_in_at"])
    return timezone.localtime(start).date() if start is not None else original_day


def pending_for_day(employee, work_day):
    for correction in CorrectionRequest.objects.filter(
        employee=employee, status=CorrectionRequest.Status.PENDING,
    ):
        try:
            target_day = proposal_work_day(correction.proposal, correction.work_date)
        except (KeyError, CorrectionError):
            target_day = correction.work_date
        if work_day in (correction.work_date, target_day):
            return True
    return False


def pending_for_month(employee, target_month):
    for correction in CorrectionRequest.objects.filter(
        employee=employee, status=CorrectionRequest.Status.PENDING,
    ):
        try:
            target_day = proposal_work_day(correction.proposal, correction.work_date)
        except (KeyError, CorrectionError):
            target_day = correction.work_date
        days = (correction.work_date,
                target_day)
        if any(day.year == target_month.year and day.month == target_month.month for day in days):
            return True
    return False


def current_values(session):
    """現在の有効値を修正案と同じ形式で取得。"""

    if session is None:
        return {
            "clock_in_at": None,
            "clock_out_at": None,
            "breaks": [],
        }

    breaks = BreakInterval.objects.filter(
        work_session=session,
    ).order_by("started_at", "pk")

    return {
        "clock_in_at": _iso(session.clock_in_at),
        "clock_out_at": _iso(session.clock_out_at),
        "breaks": [
            {
                "started_at": _iso(item.started_at),
                "ended_at": _iso(item.ended_at),
            }
            for item in breaks
        ],
    }


def is_month_finalized(employee, work_day):
    """対象勤務月が確定済みか確認。"""

    return MonthlyClosing.objects.filter(
        employee=employee,
        target_month=work_day.replace(day=1),
        status=MonthlyClosing.Status.FINALIZED,
    ).exists()


@transaction.atomic
def submit_correction(
    *,
    employee_id,
    work_day,
    expected_version,
    proposal,
    reason,
    actor_id=None,
    proxy_reason="",
    evidence="",
):
    """原記録を変更せずに修正申請を登録する。"""

    Employee = get_user_model()

    # Phase 5の打刻処理と同じ社員ロックを使用
    employee = Employee.objects.select_for_update().get(pk=employee_id)

    actor = employee if actor_id is None else Employee.objects.select_for_update().get(pk=actor_id)
    is_proxy = actor.pk != employee.pk
    if is_proxy:
        if employee.is_active or not actor.is_active or not actor.is_business_admin:
            raise CorrectionError("停止中社員の代理申請権限がありません。")
        proxy_reason = proxy_reason.strip()
        evidence = evidence.strip()
        if not 1 <= len(proxy_reason) <= 1000 or not 1 <= len(evidence) <= 1000:
            raise CorrectionError("本人申請ができない理由と確認資料を各1000文字以内で入力してください。")
    elif not employee.is_active:
        raise CorrectionError("無効なアカウントです。")

    if work_day > timezone.localdate():
        raise CorrectionError("未来の勤務日は申請できません。")

    if is_month_finalized(employee, work_day):
        raise CorrectionError("確定済みの勤務月は修正申請できません。")

    session = (
        WorkSession.objects.select_for_update()
        .filter(
            employee=employee,
            work_date=work_day,
        )
        .first()
    )

    current_version = session.version if session else 0

    if current_version != expected_version:
        raise CorrectionError(
            "勤務記録が変更されました。" "内容を確認し直してください。"
        )

    if session is not None:
        if CorrectionRequest.objects.filter(
            employee=employee, work_date=work_day,
            status=CorrectionRequest.Status.PENDING,
        ).exists():
            raise CorrectionError("この勤務には審査中の申請があります。")

    normalized = validate_proposal(
        proposal,
        work_day,
    )

    proposed_start = _parse_datetime(normalized["clock_in_at"])
    proposed_end = _parse_datetime(normalized["clock_out_at"])
    target_day = proposal_work_day(normalized, work_day)
    if target_day != work_day and is_month_finalized(employee, target_day):
        raise CorrectionError("移動先の勤務月は確定済みです。")
    if target_day != work_day:
        destination = WorkSession.objects.select_for_update().filter(
            employee=employee, work_date=target_day,
        ).first()
        if destination and destination.status != WorkSession.Status.NO_RECORD:
            raise CorrectionError("移動先に有効な勤務があります。")
    if proposed_start is not None:
        if not is_employed_on(employee, target_day):
            raise CorrectionError("在籍期間外の勤務は申請できません。")
        if overlapping_sessions(
            employee, proposed_start, proposed_end,
            exclude_session_id=session.pk if session else None,
        ):
            raise CorrectionError("別の勤務と時間が重複しています。")

    if pending_for_day(employee, work_day) or pending_for_day(employee, target_day):
        raise CorrectionError("関係する勤務日に審査中の申請があります。")

    if normalized == current_values(session):
        raise CorrectionError("現在の勤務記録から変更がありません。")

    reason = reason.strip()

    if not 1 <= len(reason) <= 500:
        raise CorrectionError("申請理由は1〜500文字で入力してください。")

    before_snapshot = current_values(session)
    previous_request = CorrectionRequest.objects.filter(
        employee=employee, work_date=work_day,
        status__in=[CorrectionRequest.Status.RETURNED, CorrectionRequest.Status.WITHDRAWN],
    ).order_by("-created_at", "-pk").first()

    correction = CorrectionRequest.objects.create(
        work_session=session,
        employee=employee,
        work_date=work_day,
        related_request=previous_request,
        requested_by=actor,
        original_version=session.version if session else None,
        proposal=normalized,
        reason=reason,
        is_proxy=is_proxy,
        proxy_reason=proxy_reason if is_proxy else "",
        evidence=evidence if is_proxy else "",
        status=CorrectionRequest.Status.PENDING,
    )

    AuditLog.objects.create(
        actor=actor,
        target_employee=employee,
        action=AuditLog.Action.CORRECTION_SUBMIT,
        target_model="CorrectionRequest",
        target_id=str(correction.pk),
        before_data=before_snapshot,
        after_data={
            "status": CorrectionRequest.Status.PENDING,
            "proposal": normalized,
        },
        reason=reason,
        details={
            "work_date": work_day.isoformat(),
            "original_version": session.version if session else None,
            "related_request_id": previous_request.pk if previous_request else None,
            "target_work_date": target_day.isoformat(),
            "is_proxy": is_proxy,
            "proxy_reason": proxy_reason if is_proxy else "",
            "evidence": evidence if is_proxy else "",
        },
    )

    notify_correction_submitted(correction)

    return correction


@transaction.atomic
def withdraw_correction(*, employee_id, request_id, reason=""):
    """Normal and proxy withdrawals use distinct actor checks."""

    Employee = get_user_model()

    actor = Employee.objects.select_for_update().get(pk=employee_id)

    if not actor.is_active:
        raise CorrectionError("無効なアカウントです。")

    correction = CorrectionRequest.objects.filter(
        pk=request_id,
    ).first()

    if correction is None:
        raise CorrectionError("対象の申請が見つかりません。")

    employee = Employee.objects.select_for_update().get(pk=correction.employee_id)

    # ロック順序を打刻・申請処理と揃える
    if correction.work_session_id:
        WorkSession.objects.select_for_update().get(pk=correction.work_session_id)

    correction = CorrectionRequest.objects.select_for_update().get(pk=correction.pk)

    if correction.status != CorrectionRequest.Status.PENDING:
        raise CorrectionError("審査中の申請だけ取り下げできます。")

    if correction.is_proxy:
        if not actor.is_business_admin or actor.pk == employee.pk:
            raise CorrectionError("代理申請の取下げ権限がありません。")
        author = correction.requested_by
        author_valid = author.is_active and author.is_business_admin
        if author_valid and actor.pk != author.pk:
            raise CorrectionError("有効な申請者本人だけが取り下げられます。")
        if not author_valid and actor.pk == author.pk:
            raise CorrectionError("管理権限が失効しています。")
        if not author_valid and not 1 <= len(reason.strip()) <= 500:
            raise CorrectionError("代理申請者が失効した場合は取下げ理由が必要です。")
    elif actor.pk != employee.pk or correction.requested_by_id != actor.pk:
        raise CorrectionError("本人の申請だけを取り下げられます。")

    if is_month_finalized(
        employee,
        correction.work_date,
    ):
        raise CorrectionError("確定済みの月は変更できません。")

    correction.status = CorrectionRequest.Status.WITHDRAWN
    correction.withdrawn_at = timezone.now()
    correction.withdrawn_by = actor
    correction.withdraw_reason = reason.strip() if correction.is_proxy else ""

    correction.save(
        update_fields=[
            "status",
            "withdrawn_at",
            "withdrawn_by",
            "withdraw_reason",
            "updated_at",
        ]
    )

    AuditLog.objects.create(
        actor=actor,
        target_employee=employee,
        action=AuditLog.Action.CORRECTION_WITHDRAW,
        target_model="CorrectionRequest",
        target_id=str(correction.pk),
        before_data={
            "status": CorrectionRequest.Status.PENDING,
        },
        after_data={
            "status": CorrectionRequest.Status.WITHDRAWN,
        },
        reason=reason.strip() or ("代理申請の取下げ" if correction.is_proxy else "本人による取下げ"),
        details={
            "work_date": correction.work_date.isoformat(),
        },
    )

    return correction
