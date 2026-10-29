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
from corrections.models import CorrectionRequest

from auditlog.models import AuditLog


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


def make_proposal(form, break_formset):
    """検証済みフォームを修正案JSONへ変換する。"""

    breaks = []

    for entry in break_formset.forms:
        data = entry.cleaned_data

        if not data or data.get("DELETE"):
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

    return {
        "clock_in_at": _iso(form.cleaned_data["clock_in_at"]),
        "clock_out_at": _iso(form.cleaned_data["clock_out_at"]),
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

    if start is not None:
        if timezone.localtime(start).date() != work_day:
            raise CorrectionError("出勤日時の日付が勤務日と一致しません。")

    if start is not None and end is not None:
        if end <= start:
            raise CorrectionError("退勤日時は出勤日時より後にしてください。")

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
):
    """原記録を変更せずに修正申請を登録する。"""

    Employee = get_user_model()

    # Phase 5の打刻処理と同じ社員ロックを使用
    employee = Employee.objects.select_for_update().get(pk=employee_id)

    if not employee.is_active:
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
            work_session=session,
            status=CorrectionRequest.Status.PENDING,
        ).exists():
            raise CorrectionError("この勤務には審査中の申請があります。")

    normalized = validate_proposal(
        proposal,
        work_day,
    )

    if normalized == current_values(session):
        raise CorrectionError("現在の勤務記録から変更がありません。")

    reason = reason.strip()

    if not 1 <= len(reason) <= 500:
        raise CorrectionError("申請理由は1〜500文字で入力してください。")

    # 記録がない日の申請では空の勤務を作成
    if session is None:
        session = WorkSession.objects.create(
            employee=employee,
            work_date=work_day,
            status=WorkSession.Status.NO_RECORD,
        )

    before_snapshot = current_values(session)

    correction = CorrectionRequest.objects.create(
        work_session=session,
        requested_by=employee,
        original_version=session.version,
        proposal=normalized,
        reason=reason,
        status=CorrectionRequest.Status.PENDING,
    )

    AuditLog.objects.create(
        actor=employee,
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
            "original_version": session.version,
        },
    )

    return correction


@transaction.atomic
def withdraw_correction(*, employee_id, request_id):
    """本人の審査中申請だけを取り下げる。"""

    Employee = get_user_model()

    employee = Employee.objects.select_for_update().get(pk=employee_id)

    if not employee.is_active:
        raise CorrectionError("無効なアカウントです。")

    correction = CorrectionRequest.objects.filter(
        pk=request_id,
        requested_by=employee,
    ).first()

    if correction is None:
        raise CorrectionError("対象の申請が見つかりません。")

    # ロック順序を打刻・申請処理と揃える
    WorkSession.objects.select_for_update().get(pk=correction.work_session_id)

    correction = CorrectionRequest.objects.select_for_update().get(pk=correction.pk)

    if correction.status != CorrectionRequest.Status.PENDING:
        raise CorrectionError("審査中の申請だけ取り下げできます。")

    if is_month_finalized(
        employee,
        correction.work_session.work_date,
    ):
        raise CorrectionError("確定済みの月は変更できません。")

    correction.status = CorrectionRequest.Status.WITHDRAWN
    correction.withdrawn_at = timezone.now()

    correction.save(
        update_fields=[
            "status",
            "withdrawn_at",
            "updated_at",
        ]
    )

    AuditLog.objects.create(
        actor=employee,
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
        reason="本人による取下げ",
        details={
            "work_date": (correction.work_session.work_date.isoformat()),
        },
    )

    return correction
