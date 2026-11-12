from dataclasses import dataclass
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from auditlog.models import AuditLog
from corrections.models import CorrectionRequest

from .models import (
    BreakInterval,
    ClockEvent,
    MonthlyClosing,
    WorkSession,
)
from .validation import is_employed_on, overlapping_sessions
from .incomplete import sync_incomplete_occurrences


class ClockActionError(Exception):
    """打刻の業務ルールに違反した場合のエラー。"""


@dataclass
class ClockResult:
    event: ClockEvent
    session: WorkSession
    already_recorded: bool = False


def _month_start(work_date: date) -> date:
    """勤務日から対象月の1日を取得する。"""

    return work_date.replace(day=1)


def _is_finalized(employee, work_date: date) -> bool:
    """対象月が確定済みか確認する。"""

    return MonthlyClosing.objects.filter(
        employee=employee,
        target_month=_month_start(work_date),
        status=MonthlyClosing.Status.FINALIZED,
    ).exists()


def _has_pending_request(session: WorkSession) -> bool:
    """対象勤務に審査中の修正申請があるか確認する。"""

    return CorrectionRequest.objects.filter(
        employee=session.employee, work_date=session.work_date,
        status=CorrectionRequest.Status.PENDING,
    ).exists()


@transaction.atomic
def record_clock_action(
    *,
    employee_id: int,
    kind: str,
    operation_id,
    expected_work_date=None,
    expected_session_id=None,
    expected_version=None,
) -> ClockResult:
    """4種類の打刻を安全に保存する。"""

    Employee = get_user_model()

    # PostgreSQLでは同じ社員の操作を直列化する
    employee = Employee.objects.select_for_update().get(pk=employee_id)

    if not employee.is_active:
        raise ClockActionError("利用できないアカウントです。")

    valid_kinds = {value for value, label in ClockEvent.Kind.choices}

    if kind not in valid_kinds:
        raise ClockActionError("不正な打刻種別です。")

    request_snapshot = (
        {
            "work_date": expected_work_date.isoformat(),
            "session_id": expected_session_id,
            "version": expected_version,
        }
        if expected_work_date is not None else {}
    )

    # 同じ操作IDでの再送か確認する
    existing_event = (
        ClockEvent.objects.select_related("work_session")
        .filter(operation_id=operation_id)
        .first()
    )

    if existing_event is not None:
        if (
            existing_event.work_session.employee_id != employee.id
            or existing_event.kind != kind
            or existing_event.request_snapshot != request_snapshot
        ):
            raise ClockActionError("この操作IDは使用できません。")

        return ClockResult(
            event=existing_event,
            session=existing_event.work_session,
            already_recorded=True,
        )

    # 記録時刻はサーバーから取得する
    now = timezone.now().replace(microsecond=0)
    today = timezone.localtime(now).date()

    # 同時進行中の勤務を取得する
    session = (
        WorkSession.objects.select_for_update()
        .filter(
            employee=employee,
            status__in=[
                WorkSession.Status.WORKING,
                WorkSession.Status.ON_BREAK,
            ],
        )
        .first()
    )

    if expected_work_date is not None:
        if kind == ClockEvent.Kind.CLOCK_IN:
            if expected_work_date != today:
                raise ClockActionError("古い出勤画面です。画面を開き直してください。")
            current = session or WorkSession.objects.filter(
                employee=employee, work_date=today
            ).first()
        else:
            current = session
        if (
            (current.pk if current else None) != expected_session_id
            or (current.version if current else None) != expected_version
            or (current.work_date if current else today) != expected_work_date
        ):
            raise ClockActionError("勤務情報が更新されました。画面を開き直してください。")

    before_data = {}
    update_fields = []

    if kind == ClockEvent.Kind.CLOCK_IN:

        if session is not None:
            raise ClockActionError(
                "進行中の勤務があります。" "出勤を重複して記録できません。"
            )

        if _is_finalized(employee, today):
            raise ClockActionError("確定済みの月には打刻できません。")

        from corrections.services import pending_for_day
        if pending_for_day(employee, today):
            raise ClockActionError("関係する勤務日の修正申請が審査中です。")

        if not is_employed_on(employee, today):
            raise ClockActionError("在籍期間外の日には出勤できません。")

        if overlapping_sessions(employee, now, None):
            raise ClockActionError("別の勤務と時間が重複しています。")

        existing_today = (
            WorkSession.objects
            .select_for_update()
            .filter(
                employee=employee,
                work_date=today,
            )
            .first()
        )

        if existing_today is not None:

            # 修正申請の審査中は出勤できない
            if CorrectionRequest.objects.filter(
                employee=employee, work_date=today,
                status=CorrectionRequest.Status.PENDING,
            ).exists():
                raise ClockActionError(
                    "修正申請の審査中は打刻できません。"
                )

            # 原打刻がなく、勤務値もない仮レコード
            reusable = (
                existing_today.status
                == WorkSession.Status.NO_RECORD
                and existing_today.clock_in_at is None
                and existing_today.clock_out_at is None
                and not ClockEvent.objects.filter(
                    work_session=existing_today
                ).exists()
                and not BreakInterval.objects.filter(
                    work_session=existing_today
                ).exists()
            )

            if not reusable:
                raise ClockActionError(
                    "この勤務日の記録は既に存在します。"
                )

            session = existing_today
            session.clock_in_at = now
            session.status = WorkSession.Status.WORKING
            session.version += 1

            session.save(
                update_fields=[
                    "clock_in_at",
                    "status",
                    "version",
                    "updated_at",
                ]
            )

        else:
            session = WorkSession.objects.create(
                employee=employee,
                work_date=today,
                clock_in_at=now,
                status=WorkSession.Status.WORKING,
            )

    else:

        if session is None:
            raise ClockActionError("操作できる勤務がありません。")

        if _is_finalized(employee, session.work_date):
            raise ClockActionError("確定済みの勤務は変更できません。")

        if _has_pending_request(session):
            raise ClockActionError("修正申請の審査中は打刻できません。")
        from corrections.services import pending_for_day
        if pending_for_day(employee, session.work_date):
            raise ClockActionError("関係する勤務日の修正申請が審査中です。")

        before_data = {
            "status": session.status,
            "version": session.version,
        }

        if kind == ClockEvent.Kind.BREAK_START:

            if session.status != WorkSession.Status.WORKING:
                raise ClockActionError("休憩開始は勤務中のみ可能です。")

            if now <= session.clock_in_at:
                raise ClockActionError("休憩開始日時が出勤日時以前です。")

            last_break = (
                BreakInterval.objects.filter(work_session=session)
                .order_by("-started_at")
                .first()
            )

            if last_break is not None:
                if last_break.ended_at is None or now <= last_break.ended_at:
                    raise ClockActionError("休憩時間が重複しています。")

            BreakInterval.objects.create(
                work_session=session,
                started_at=now,
            )

            session.status = WorkSession.Status.ON_BREAK
            update_fields = ["status"]

        elif kind == ClockEvent.Kind.BREAK_END:

            if session.status != WorkSession.Status.ON_BREAK:
                raise ClockActionError("休憩中ではありません。")

            current_break = (
                BreakInterval.objects.select_for_update()
                .filter(
                    work_session=session,
                    ended_at__isnull=True,
                )
                .first()
            )

            if current_break is None:
                raise ClockActionError("終了していない休憩が見つかりません。")

            if now <= current_break.started_at:
                raise ClockActionError("休憩終了日時が開始日時以前です。")

            current_break.ended_at = now
            current_break.save(update_fields=["ended_at"])

            session.status = WorkSession.Status.WORKING
            update_fields = ["status"]

        elif kind == ClockEvent.Kind.CLOCK_OUT:

            if session.status != WorkSession.Status.WORKING:
                raise ClockActionError("休憩終了後に退勤してください。")

            if now <= session.clock_in_at:
                raise ClockActionError("退勤日時が出勤日時以前です。")

            breaks = list(
                BreakInterval.objects.filter(work_session=session).order_by(
                    "started_at"
                )
            )

            previous_end = session.clock_in_at

            for interval in breaks:
                if interval.ended_at is None:
                    raise ClockActionError("終了していない休憩があります。")

                if (
                    interval.started_at < previous_end
                    or interval.ended_at <= interval.started_at
                    or interval.ended_at > now
                ):
                    raise ClockActionError("休憩日時に矛盾があります。")

                previous_end = interval.ended_at

            session.clock_out_at = now
            session.status = WorkSession.Status.COMPLETED
            session.incomplete_notified_version = None
            update_fields = ["clock_out_at", "status", "incomplete_notified_version"]

        # 打刻による更新版を進める
        session.version += 1

        session.save(update_fields=(update_fields + ["version", "updated_at"]))

    # 原打刻を追加する（後から変更しない）
    event = ClockEvent.objects.create(
        work_session=session,
        kind=kind,
        recorded_at=now,
        operation_id=operation_id,
        request_snapshot=request_snapshot,
    )

    sync_incomplete_occurrences(session, now=now)

    # 同じトランザクションで監査履歴も保存
    AuditLog.objects.create(
        actor=employee,
        target_employee=employee,
        action=AuditLog.Action.CLOCK,
        target_model="WorkSession",
        target_id=str(session.pk),
        before_data=before_data,
        after_data={
            "kind": kind,
            "status": session.status,
            "version": session.version,
            "recorded_at": now.isoformat(),
        },
        details={
            "operation_id": str(operation_id),
        },
    )

    return ClockResult(
        event=event,
        session=session,
    )
