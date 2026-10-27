import logging
import uuid
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, OperationalError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from corrections.models import CorrectionRequest

from .forms import ClockActionForm
from .models import (
    BreakInterval,
    ClockEvent,
    MonthlyClosing,
    WorkSession,
)
from .services import (
    ClockActionError,
    record_clock_action,
)

logger = logging.getLogger(__name__)


ACTION_LABELS = {
    "clock_in": "出勤",
    "clock_out": "退勤",
    "break_start": "休憩開始",
    "break_end": "休憩終了",
}


def _format_duration(seconds):
    """秒数を時間・分の表示へ変換する。"""

    minutes = seconds // 60

    hours = minutes // 60
    remaining_minutes = minutes % 60

    return f"{hours}時間{remaining_minutes:02d}分"


@never_cache
@login_required
def home(request):
    """社員の打刻ホーム画面。"""

    employee = request.user
    now = timezone.now()
    today = timezone.localtime(now).date()

    active_session = WorkSession.objects.filter(
        employee=employee,
        status__in=[
            WorkSession.Status.WORKING,
            WorkSession.Status.ON_BREAK,
        ],
    ).first()

    if active_session is not None:
        session = active_session
    else:
        session = WorkSession.objects.filter(
            employee=employee,
            work_date=today,
        ).first()

    breaks = []
    last_event = None

    available_actions = []
    pending_request = False
    is_finalized = False

    break_seconds = None
    work_seconds = None

    if session is not None:

        breaks = list(
            BreakInterval.objects.filter(work_session=session).order_by("started_at")
        )

        last_event = (
            ClockEvent.objects.filter(work_session=session)
            .order_by("-recorded_at", "-id")
            .first()
        )

        pending_request = CorrectionRequest.objects.filter(
            work_session=session,
            status=CorrectionRequest.Status.PENDING,
        ).exists()

        target_date = session.work_date

    else:
        target_date = today

    month_start = date(
        target_date.year,
        target_date.month,
        1,
    )

    is_finalized = MonthlyClosing.objects.filter(
        employee=employee,
        target_month=month_start,
        status=MonthlyClosing.Status.FINALIZED,
    ).exists()

    if not pending_request and not is_finalized:

        if session is None:
            available_actions = ["clock_in"]

        elif session.status == WorkSession.Status.WORKING:
            available_actions = [
                "break_start",
                "clock_out",
            ]

        elif session.status == WorkSession.Status.ON_BREAK:
            available_actions = ["break_end"]

    # 退勤済みなら実働時間を計算
    if (
        session is not None
        and session.status == WorkSession.Status.COMPLETED
        and session.clock_in_at
        and session.clock_out_at
        and all(item.ended_at is not None for item in breaks)
    ):

        # 休憩が勤務内に収まるかも確認
        previous_end = session.clock_in_at
        valid = session.clock_out_at > session.clock_in_at

        total_break = 0

        for item in breaks:

            if (
                item.started_at < previous_end
                or item.ended_at <= item.started_at
                or item.ended_at > session.clock_out_at
            ):
                valid = False
                break

            total_break += int((item.ended_at - item.started_at).total_seconds())
            previous_end = item.ended_at

        if valid:
            total_work = (
                int((session.clock_out_at - session.clock_in_at).total_seconds())
                - total_break
            )

            if total_work >= 0:
                break_seconds = total_break
                work_seconds = total_work

    buttons = [
        {
            "kind": action,
            "label": ACTION_LABELS[action],
            "operation_id": str(uuid.uuid4()),
        }
        for action in available_actions
    ]

    context = {
        "now": now,
        "today": today,
        "session": session,
        "breaks": breaks,
        "last_event": last_event,
        "buttons": buttons,
        "pending_request": pending_request,
        "is_finalized": is_finalized,
        "is_overnight": (
            session is not None
            and session.work_date < today
            and session.status
            in [
                WorkSession.Status.WORKING,
                WorkSession.Status.ON_BREAK,
            ]
        ),
        "break_duration": (
            _format_duration(break_seconds) if break_seconds is not None else None
        ),
        "work_duration": (
            _format_duration(work_seconds) if work_seconds is not None else None
        ),
    }

    return render(
        request,
        "employee/home.html",
        context,
    )


@never_cache
@login_required
@require_POST
def clock_action(request):
    """打刻を受け付けるPOST専用ビュー。"""

    form = ClockActionForm(request.POST)

    if not form.is_valid():
        messages.error(
            request,
            "打刻情報が正しくありません。" "画面を再読み込みしてください。",
        )
        return redirect("attendance:home")

    kind = form.cleaned_data["action"]
    operation_id = form.cleaned_data["operation_id"]

    try:
        result = record_clock_action(
            employee_id=request.user.pk,
            kind=kind,
            operation_id=operation_id,
        )

    except ClockActionError as exc:
        messages.error(request, str(exc))

    except (IntegrityError, OperationalError):
        logger.exception(
            "打刻のDB処理に失敗しました: employee_id=%s kind=%s",
            request.user.pk,
            kind,
        )

        messages.warning(
            request,
            "通信または保存処理の結果を確認できませんでした。"
            "最新の勤務状態を確認してから操作してください。",
        )

    else:
        recorded_time = timezone.localtime(result.event.recorded_at).strftime(
            "%Y/%m/%d %H:%M:%S"
        )

        if result.already_recorded:
            messages.info(
                request,
                f"保存済みの打刻を確認しました。" f" 記録時刻：{recorded_time}",
            )
        else:
            messages.success(
                request,
                f"{ACTION_LABELS[kind]}を記録しました。" f" 記録時刻：{recorded_time}",
            )

    return redirect("attendance:home")
