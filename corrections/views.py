"""勤怠修正申請・確認・履歴・取下げ画面。"""

import logging
import secrets
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.http import Http404
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from attendance.models import (
    BreakInterval,
    WorkSession,
)

from .forms import (
    DATETIME_FORMAT,
    CorrectionBreakFormSet,
    CorrectionValuesForm,
)
from .models import CorrectionRequest
from .services import (
    CorrectionError,
    current_values,
    is_month_finalized,
    make_proposal,
    pending_for_day,
    proposal_work_day,
    submit_correction,
    validate_proposal,
    withdraw_correction,
)

logger = logging.getLogger(__name__)

SIGNING_SALT = "attendance-correction-v1"
CONFIRM_MAX_AGE = 15 * 60

CONFIRM_NONCE_SESSION_KEY = "correction_confirm_nonce"


# ==========================================
# 共通処理
# ==========================================


def _work_day(year, month, day):
    """URLの日付を検証する。"""

    try:
        return date(year, month, day)

    except ValueError as exc:
        raise Http404("指定された日付は存在しません。") from exc


def _field_initial(value):
    """datetime-local入力欄の初期値を作る。"""

    if value is None:
        return None

    return timezone.localtime(value).strftime(DATETIME_FORMAT)


def _initial_values(session):
    """現在の有効な出退勤日時を取得する。"""

    if session is None:
        return {}

    return {
        "clock_in_at": _field_initial(session.clock_in_at),
        "clock_out_at": _field_initial(session.clock_out_at),
    }


def _initial_breaks(session):
    """現在の休憩記録を入力フォーム用に整える。"""

    if session is None:
        return [{}]

    breaks = BreakInterval.objects.filter(
        work_session=session,
    ).order_by(
        "started_at",
        "pk",
    )

    rows = [
        {
            "started_at": _field_initial(item.started_at),
            "ended_at": _field_initial(item.ended_at),
        }
        for item in breaks
    ]

    # 追加用の空行を用意する
    if len(rows) < 20:
        rows.append({})

    return rows


def _display_datetime(value):
    """申請内容の日時を画面表示用に変換する。"""

    if value is None:
        return "設定なし"

    parsed = parse_datetime(value)

    if parsed is None:
        return "日時を確認できません"

    if timezone.is_naive(parsed):
        return "タイムゾーンを確認できません"

    return timezone.localtime(parsed).strftime("%Y/%m/%d %H:%M:%S")


def _display_proposal(proposal):
    """修正案を確認画面用に整える。"""

    if not isinstance(proposal, dict):
        proposal = {}

    breaks = proposal.get("breaks", [])

    if not isinstance(breaks, list):
        breaks = []

    break_rows = []

    for number, item in enumerate(
        breaks,
        start=1,
    ):
        if not isinstance(item, dict):
            continue

        break_rows.append(
            {
                "number": number,
                "start": _display_datetime(item.get("started_at")),
                "end": _display_datetime(item.get("ended_at")),
            }
        )

    return {
        "clock_in": _display_datetime(proposal.get("clock_in_at")),
        "clock_out": _display_datetime(proposal.get("clock_out_at")),
        "breaks": break_rows,
    }


# ==========================================
# 署名付き確認情報の検証
# ==========================================


def _verify_confirm_token(
    request,
    token,
    employee,
    work_day,
):
    """確認情報の署名・期限・本人・nonceを検証する。"""

    try:
        payload = signing.loads(
            token,
            salt=SIGNING_SALT,
            max_age=CONFIRM_MAX_AGE,
        )

    except signing.BadSignature as exc:
        raise CorrectionError("確認情報が無効か、有効期限が切れています。") from exc

    if not isinstance(payload, dict):
        raise CorrectionError("確認情報の形式が不正です。")

    if payload.get("user_id") != employee.pk:
        raise CorrectionError("確認情報がログイン社員と一致しません。")

    if payload.get("work_day") != work_day.isoformat():
        raise CorrectionError("確認情報の勤務日が一致しません。")

    expected_version = payload.get("expected_version")

    if type(expected_version) is not int or expected_version < 0:
        raise CorrectionError("勤務データのバージョンが不正です。")

    if not isinstance(
        payload.get("proposal"),
        dict,
    ):
        raise CorrectionError("修正案の形式が不正です。")

    if not isinstance(
        payload.get("reason"),
        str,
    ):
        raise CorrectionError("申請理由の形式が不正です。")

    # 二重送信防止用の識別子
    token_nonce = payload.get("nonce")

    session_nonce = request.session.get(CONFIRM_NONCE_SESSION_KEY)

    if not (
        isinstance(token_nonce, str)
        and isinstance(session_nonce, str)
        and token_nonce
        and session_nonce
    ):
        raise CorrectionError("確認情報の有効性を確認できません。")

    if not secrets.compare_digest(
        token_nonce,
        session_nonce,
    ):
        raise CorrectionError(
            "確認情報が一致しません。" "入力内容を確認し直してください。"
        )

    return payload


# ==========================================
# 修正申請の入力・確認・確定
# ==========================================


@never_cache
@login_required
def correction_create(request, year, month, day):
    """修正申請の入力・確認・確定を行う。"""

    work_day = _work_day(
        year,
        month,
        day,
    )

    if work_day > timezone.localdate():
        raise Http404("未来の勤務日は申請できません。")

    employee = request.user

    session = WorkSession.objects.filter(
        employee=employee,
        work_date=work_day,
    ).first()

    # 月次確定済みの場合は申請不可
    if is_month_finalized(employee, work_day):
        messages.error(
            request,
            "確定済みの勤務月は申請できません。",
        )

        return redirect(
            "attendance:daily",
            year=year,
            month=month,
            day=day,
        )

    # 同じ勤務に審査中の申請がある場合
    pending = CorrectionRequest.objects.filter(
        employee=employee, work_date=work_day,
        status=CorrectionRequest.Status.PENDING,
    ).first()
    if pending is not None:
        messages.info(request, "この勤務には審査中の申請があります。")
        return redirect("corrections:detail", pk=pending.pk)

    if pending_for_day(employee, work_day):
        messages.info(request, "この勤務日には審査中の申請があります。")
        return redirect("attendance:daily", year=year, month=month, day=day)

    # --------------------------------------
    # 申請の最終確定
    # --------------------------------------

    if request.method == "POST" and "confirm_token" in request.POST and request.POST.get("back") == "1":
        try:
            payload = _verify_confirm_token(request, request.POST["confirm_token"], employee, work_day)
        except CorrectionError as exc:
            messages.error(request, str(exc))
            return redirect("corrections:create", year=year, month=month, day=day)
        proposal = payload["proposal"]
        form = CorrectionValuesForm(initial={
            "clock_in_at": _field_initial(parse_datetime(proposal["clock_in_at"])) if proposal.get("clock_in_at") else None,
            "clock_out_at": _field_initial(parse_datetime(proposal["clock_out_at"])) if proposal.get("clock_out_at") else None,
            "reason": payload["reason"],
        })
        break_formset = CorrectionBreakFormSet(initial=[{
            "started_at": _field_initial(parse_datetime(item["started_at"])) if item.get("started_at") else None,
            "ended_at": _field_initial(parse_datetime(item["ended_at"])) if item.get("ended_at") else None,
        } for item in proposal.get("breaks", [])] or [{}], prefix="breaks")
        return render(request, "corrections/form.html", {
            "work_day": work_day, "form": form, "break_formset": break_formset, "session": session,
        })

    if request.method == "POST" and "confirm_token" in request.POST:

        token = request.POST.get(
            "confirm_token",
            "",
        )

        try:
            payload = _verify_confirm_token(
                request,
                token,
                employee,
                work_day,
            )

            result = submit_correction(
                employee_id=employee.pk,
                work_day=work_day,
                expected_version=(payload["expected_version"]),
                proposal=payload["proposal"],
                reason=payload["reason"],
            )

        except (
            CorrectionError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:

            logger.info(
                "修正申請の確認に失敗: " "employee_id=%s work_day=%s error=%s",
                employee.pk,
                work_day,
                str(exc),
            )

            messages.error(
                request,
                "申請を確定できませんでした。" "内容を再確認してください。",
            )

            return redirect(
                "corrections:create",
                year=year,
                month=month,
                day=day,
            )

        except (IntegrityError, OperationalError):

            logger.exception(
                "修正申請のDB処理に失敗: " "employee_id=%s work_day=%s",
                employee.pk,
                work_day,
            )

            messages.error(
                request,
                "申請の保存結果を確認できませんでした。" "申請履歴を確認してください。",
            )

            return redirect(
                "corrections:list",
            )

        # 保存成功後にnonceを破棄する
        request.session.pop(
            CONFIRM_NONCE_SESSION_KEY,
            None,
        )

        messages.success(
            request,
            "修正申請を受け付けました。",
        )

        return redirect(
            "corrections:detail",
            pk=result.pk,
        )

    # --------------------------------------
    # 申請入力・内容確認
    # --------------------------------------

    if request.method == "POST":

        form = CorrectionValuesForm(request.POST)

        break_formset = CorrectionBreakFormSet(
            request.POST,
            prefix="breaks",
        )

        form_valid = form.is_valid()
        breaks_valid = break_formset.is_valid()

        if form_valid and breaks_valid:

            try:
                proposal = validate_proposal(
                    make_proposal(
                        form,
                        break_formset,
                    ),
                    work_day,
                )

                # 変更内容がない申請は禁止
                if proposal == current_values(session):
                    raise CorrectionError("変更内容がありません。")

                expected_version = session.version if session else 0

                # 確認画面ごとの識別子
                nonce = secrets.token_urlsafe(32)

                # セッションへ保存
                request.session[CONFIRM_NONCE_SESSION_KEY] = nonce

                # 署名付きの確認情報
                token = signing.dumps(
                    {
                        "user_id": employee.pk,
                        "work_day": work_day.isoformat(),
                        "expected_version": expected_version,
                        "proposal": proposal,
                        "reason": (form.cleaned_data["reason"]),
                        "nonce": nonce,
                    },
                    salt=SIGNING_SALT,
                )

                return render(
                    request,
                    "corrections/confirm.html",
                    {
                        "work_day": work_day,
                        "target_day": proposal_work_day(proposal, work_day),
                        "proposal_display": (_display_proposal(proposal)),
                        "current_display": _display_proposal(current_values(session)),
                        "reason": (form.cleaned_data["reason"]),
                        "confirm_token": token,
                    },
                )

            except CorrectionError as exc:
                form.add_error(
                    None,
                    str(exc),
                )

    else:

        form = CorrectionValuesForm(
            initial=_initial_values(session),
        )

        break_formset = CorrectionBreakFormSet(
            initial=_initial_breaks(session),
            prefix="breaks",
        )

    return render(
        request,
        "corrections/form.html",
        {
            "work_day": work_day,
            "form": form,
            "break_formset": break_formset,
            "session": session,
        },
    )


# ==========================================
# 修正申請履歴一覧
# ==========================================


@never_cache
@login_required
def correction_list(request):
    """ログイン社員本人の申請履歴一覧。"""

    status_filter = request.GET.get(
        "status",
        "all",
    )

    allowed_statuses = {
        "all",
        "pending",
        "approved",
        "returned",
        "withdrawn",
    }

    if status_filter not in allowed_statuses:
        status_filter = "all"

    queryset = (
        CorrectionRequest.objects.filter(requested_by=request.user)
        .select_related("employee", "work_session")
        .order_by(
            "-created_at",
            "-pk",
        )
    )

    if status_filter != "all":
        queryset = queryset.filter(status=status_filter)

    paginator = Paginator(
        queryset,
        10,
    )

    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "corrections/list.html",
        {
            "page_obj": page_obj,
            "status_filter": status_filter,
        },
    )


# ==========================================
# 修正申請詳細
# ==========================================


@never_cache
@login_required
def correction_detail(request, pk):
    """ログイン社員本人の修正申請詳細。"""

    correction = get_object_or_404(
        CorrectionRequest.objects.select_related("employee", "work_session"),
        pk=pk,
        requested_by=request.user,
    )

    return render(
        request,
        "corrections/detail.html",
        {
            "correction": correction,
            "proposal_display": (_display_proposal(correction.proposal)),
        },
    )


# ==========================================
# 修正申請の取下げ
# ==========================================


@never_cache
@login_required
@require_POST
def correction_withdraw(request, pk):
    """本人の審査中申請のみ取り下げる。"""

    # 他人の申請にはアクセスできない
    get_object_or_404(
        CorrectionRequest,
        pk=pk,
        requested_by=request.user,
    )

    try:
        withdraw_correction(
            employee_id=request.user.pk,
            request_id=pk,
        )

    except CorrectionError as exc:
        messages.error(
            request,
            str(exc),
        )

    except (IntegrityError, OperationalError):

        logger.exception(
            "修正申請の取下げに失敗: " "employee_id=%s request_id=%s",
            request.user.pk,
            pk,
        )

        messages.error(
            request,
            "取下げの保存結果を確認できませんでした。" "申請状態を確認してください。",
        )

    else:
        messages.success(
            request,
            "修正申請を取り下げました。",
        )

    return redirect(
        "corrections:detail",
        pk=pk,
    )
