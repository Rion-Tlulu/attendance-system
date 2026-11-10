"""社員の打刻ホーム・打刻処理・月次勤怠・日別詳細ビュー。"""

import logging
import uuid
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from corrections.models import CorrectionRequest

from .forms import ClockActionForm, MonthSelectForm
from .models import (
    BreakInterval,
    ClockEvent,
    MonthlyClosing,
    WorkSession,
)
from .reporting import (
    build_comparison_rows,
    build_daily_row,
    build_monthly_report,
    calculate_duration,
    format_datetime,
    format_duration,
    get_breaks,
    get_corrections,
    get_daily_session,
)
from .services import (
    ClockActionError,
    record_clock_action,
)

from .chart_data import build_work_hours_chart

logger = logging.getLogger(__name__)


ACTION_LABELS = {
    ClockEvent.Kind.CLOCK_IN: "出勤",
    ClockEvent.Kind.CLOCK_OUT: "退勤",
    ClockEvent.Kind.BREAK_START: "休憩開始",
    ClockEvent.Kind.BREAK_END: "休憩終了",
}


# ==================================================
# Phase 5：打刻ホーム
# ==================================================


@never_cache
@login_required
def home(request):
    """ログイン社員の打刻ホーム画面。"""

    employee = request.user

    now = timezone.now()
    today = timezone.localtime(now).date()

    # 前日以前から続いている勤務を優先する
    session = WorkSession.objects.filter(
        employee=employee,
        status__in=[
            WorkSession.Status.WORKING,
            WorkSession.Status.ON_BREAK,
        ],
    ).first()

    # 進行中の勤務がなければ本日分を取得
    if session is None:
        session = WorkSession.objects.filter(
            employee=employee,
            work_date=today,
        ).first()

    breaks = []
    last_event = None
    pending_request = False
    available_actions = []

    if session is not None:

        # 現在の勤務に紐づく休憩
        breaks = list(
            BreakInterval.objects.filter(
                work_session=session,
            ).order_by(
                "started_at",
                "pk",
            )
        )

        # 最後に記録された原打刻
        last_event = (
            ClockEvent.objects.filter(work_session=session)
            .order_by("-recorded_at", "-pk")
            .first()
        )

        # 修正申請の審査中か確認
        pending_request = CorrectionRequest.objects.filter(
            work_session=session,
            status=CorrectionRequest.Status.PENDING,
        ).exists()

        target_date = session.work_date

    else:
        target_date = today

    # 対象勤務月が確定済みか確認
    is_finalized = MonthlyClosing.objects.filter(
        employee=employee,
        target_month=target_date.replace(day=1),
        status=MonthlyClosing.Status.FINALIZED,
    ).exists()

    # ----------------------------------------------
    # 勤務状態に応じた打刻ボタン
    # ----------------------------------------------

    if not pending_request and not is_finalized:

        if session is None:
            available_actions = [
                ClockEvent.Kind.CLOCK_IN,
            ]

        elif session.status == WorkSession.Status.WORKING:
            available_actions = [
                ClockEvent.Kind.BREAK_START,
                ClockEvent.Kind.CLOCK_OUT,
            ]

        elif session.status == WorkSession.Status.ON_BREAK:
            available_actions = [
                ClockEvent.Kind.BREAK_END,
            ]

        elif session.status == WorkSession.Status.NO_RECORD:

            if (
                session.clock_in_at is None
                and session.clock_out_at is None
                and not ClockEvent.objects.filter(work_session=session).exists()
                and not BreakInterval.objects.filter(work_session=session).exists()
            ):
                available_actions = [
                    ClockEvent.Kind.CLOCK_IN,
                ]

    # ----------------------------------------------
    # 実働・休憩時間の計算
    # Phase 6の共通計算処理を使用
    # ----------------------------------------------

    duration = calculate_duration(
        session,
        breaks,
    )

    break_duration = (
        format_duration(duration.break_seconds) if duration.complete else None
    )

    work_duration = (
        format_duration(duration.work_seconds) if duration.complete else None
    )

    # ----------------------------------------------
    # 打刻ボタンと操作ID
    # ----------------------------------------------

    buttons = [
        {
            "kind": kind,
            "label": ACTION_LABELS[kind],
            "operation_id": str(uuid.uuid4()),
        }
        for kind in available_actions
    ]

    # ----------------------------------------------
    # 新UI表示用：操作種類ごとに整理
    # ----------------------------------------------

    action_buttons = {button["kind"]: button for button in buttons}

    # ----------------------------------------------
    # 現在の勤務に紐づく原打刻履歴
    # ----------------------------------------------

    clock_events = []

    if session is not None:
        clock_events = list(
            ClockEvent.objects.filter(
                work_session=session,
            ).order_by(
                "recorded_at",
                "pk",
            )
        )

    # ----------------------------------------------
    # テンプレートへ渡す情報
    # ----------------------------------------------

    context = {
        "now": now,
        "today": today,
        "session": session,
        "action_buttons": action_buttons,
        "clock_events": clock_events,
        "breaks": breaks,
        "last_event": last_event,
        "buttons": buttons,
        "pending_request": pending_request,
        "is_finalized": is_finalized,
        "is_overnight": bool(
            session is not None
            and session.work_date < today
            and session.status
            in (
                WorkSession.Status.WORKING,
                WorkSession.Status.ON_BREAK,
            )
        ),
        "break_duration": break_duration,
        "work_duration": work_duration,
    }

    return render(
        request,
        "employee/home.html",
        context,
    )


# ==================================================
# Phase 5：打刻処理（POST専用）
# ==================================================


@never_cache
@login_required
@require_POST
def clock_action(request):
    """出勤・休憩開始・休憩終了・退勤を記録する。"""

    form = ClockActionForm(request.POST)

    # 入力値を検証
    if not form.is_valid():

        messages.error(
            request,
            "打刻情報が正しくありません。" "画面を再読み込みしてください。",
        )

        return redirect("attendance:home")

    kind = form.cleaned_data["action"]
    operation_id = form.cleaned_data["operation_id"]

    try:

        # 実際の打刻処理はサービスへ委譲
        result = record_clock_action(
            employee_id=request.user.pk,
            kind=kind,
            operation_id=operation_id,
        )

    except ClockActionError as exc:

        # 勤務状態などの業務ルール違反
        messages.error(
            request,
            str(exc),
        )

    except (IntegrityError, OperationalError):

        # データベース処理の失敗
        logger.exception(
            "打刻のDB処理に失敗しました: " "employee_id=%s kind=%s",
            request.user.pk,
            kind,
        )

        messages.warning(
            request,
            "通信または保存処理の結果を"
            "確認できませんでした。"
            "最新の勤務状態を確認してから"
            "操作してください。",
        )

    else:

        recorded_time = timezone.localtime(result.event.recorded_at).strftime(
            "%Y/%m/%d %H:%M:%S"
        )

        # 同じ操作IDの再送
        if result.already_recorded:

            messages.info(
                request,
                "保存済みの打刻を確認しました。" f"記録時刻：{recorded_time}",
            )

        else:

            # 新しい打刻を保存した場合
            messages.success(
                request,
                f"{ACTION_LABELS[kind]}を記録しました。" f"記録時刻：{recorded_time}",
            )

    return redirect("attendance:home")


# ==================================================
# Phase 6：月次勤怠一覧（7日単位）
# ==================================================


@never_cache
@login_required
def monthly_attendance(request):
    """ログイン社員の月次勤怠一覧。"""

    current_month = timezone.localdate().replace(day=1)

    # ----------------------------------------------
    # 年月の取得と検証
    # ----------------------------------------------

    if "month" in request.GET:

        form = MonthSelectForm(request.GET)

        if not form.is_valid():

            return render(
                request,
                "employee/monthly.html",
                {
                    "form": form,
                    "report": None,
                },
                status=400,
            )

        target_month = form.cleaned_data["month"]

    else:

        target_month = current_month

        form = MonthSelectForm(
            initial={
                "month": target_month.strftime("%Y-%m"),
            }
        )

    # ----------------------------------------------
    # 月次勤怠の集計
    # ----------------------------------------------

    # 月の集計はページ切替とは独立して
    # 対象月の全日付を対象に行う
    report = build_monthly_report(
        request.user,
        target_month,
    )

    # ----------------------------------------------
    # 日別一覧を7日単位で表示
    # ----------------------------------------------

    paginator = Paginator(
        report.rows,
        7,
    )

    page_obj = paginator.get_page(request.GET.get("page"))

    # 新UI用：対象月の勤務完了日数
    # 所定勤務日数や出勤予定日数ではない

    if target_month.month == 12:
        next_month = date(target_month.year + 1, 1, 1)
    else:
        next_month = date(
            target_month.year,
            target_month.month + 1,
            1,
        )

    completed_work_days = WorkSession.objects.filter(
        employee=request.user,
        work_date__gte=target_month,
        work_date__lt=next_month,
        status=WorkSession.Status.COMPLETED,
    ).count()

    work_chart = build_work_hours_chart(
        request.user,
        target_month,
    )

    context = {
        "form": form,
        "report": report,
        "page_obj": page_obj,
        "completed_work_days": completed_work_days,
        "work_chart": work_chart,
    }

    return render(
        request,
        "employee/monthly.html",
        context,
    )


# ==================================================
# Phase 6：日別詳細
# ==================================================


@never_cache
@login_required
def daily_attendance(request, year, month, day):
    """ログイン社員本人の日別勤怠詳細。"""

    # ----------------------------------------------
    # 日付の妥当性を確認
    # ----------------------------------------------

    try:
        work_day = date(
            year,
            month,
            day,
        )

    except ValueError as exc:

        raise Http404("指定された日付は存在しません。") from exc

    # ----------------------------------------------
    # ログイン社員本人の勤務を取得
    # ----------------------------------------------

    session = get_daily_session(
        request.user,
        work_day,
    )

    month_start = work_day.replace(day=1)

    # ----------------------------------------------
    # 月次確定状態
    # ----------------------------------------------

    is_finalized = MonthlyClosing.objects.filter(
        employee=request.user,
        target_month=month_start,
        status=MonthlyClosing.Status.FINALIZED,
    ).exists()

    # 日別の集計と3種類の状態
    summary = build_daily_row(
        work_day,
        session,
        is_finalized,
    )

    # ----------------------------------------------
    # 休憩と修正申請履歴
    # ----------------------------------------------

    breaks = get_breaks(session)

    corrections = get_corrections(session)

    # 新UI用：審査中の修正申請を取得
    pending_correction = next(
        (
            item
            for item in corrections
            if item.status == CorrectionRequest.Status.PENDING
        ),
        None,
    )

    # 新UI用：新規修正申請を開始できるか
    is_future_day = work_day > timezone.localdate()

    can_submit_correction = (
        not is_future_day and not is_finalized and pending_correction is None
    )

    # ----------------------------------------------
    # 原打刻の取得
    # ----------------------------------------------

    if session is not None:

        original_events = list(
            ClockEvent.objects.filter(
                work_session=session,
            ).order_by(
                "recorded_at",
                "pk",
            )
        )

    else:
        original_events = []

    # ----------------------------------------------
    # 原打刻と現在の有効値の比較
    # ----------------------------------------------

    comparison_rows = build_comparison_rows(
        session,
        breaks,
        original_events,
    )

    # ----------------------------------------------
    # 休憩の詳細表示
    # ----------------------------------------------

    break_rows = []

    for number, item in enumerate(
        breaks,
        start=1,
    ):

        if item.ended_at is None:
            duration_label = "未終了"

        elif item.ended_at <= item.started_at:
            duration_label = "記録に矛盾があります"

        else:

            duration_seconds = int((item.ended_at - item.started_at).total_seconds())

            duration_label = format_duration(duration_seconds)

        break_rows.append(
            {
                "number": number,
                "start": format_datetime(item.started_at),
                "end": format_datetime(item.ended_at),
                "duration": duration_label,
            }
        )

    # ----------------------------------------------
    # 月次一覧のページ番号を引き継ぐ
    # ----------------------------------------------

    return_page = request.GET.get(
        "page",
        "1",
    )

    if not (return_page.isascii() and return_page.isdecimal()):
        return_page = "1"

    # ----------------------------------------------
    # テンプレートへ渡す情報
    # ----------------------------------------------

    context = {
        "work_day": work_day,
        "summary": summary,
        "session": session,
        "comparison_rows": comparison_rows,
        "break_rows": break_rows,
        "original_events": original_events,
        "corrections": corrections,
        "month_query": month_start.strftime("%Y-%m"),
        "return_page": return_page,
        "is_finalized": is_finalized,
        "pending_correction": pending_correction,
        "is_future_day": is_future_day,
        "can_submit_correction": can_submit_correction,
    }

    return render(
        request,
        "employee/daily.html",
        context,
    )
