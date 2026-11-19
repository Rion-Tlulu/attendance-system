"""Manager workflow for correcting an inactive employee's attendance."""

from datetime import date, datetime

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core import signing
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from attendance.models import WorkSession
from config.db_errors import SAVE_FAILURE_ERRORS, UNCONFIRMED_SAVE_MESSAGE, log_save_failure
from corrections.forms import CorrectionBreakFormSet, CorrectionValuesForm, DATETIME_FORMAT
from corrections.services import (
    CorrectionError, current_values, is_month_finalized,
    make_proposal, proposal_work_day, submit_correction, validate_proposal, withdraw_correction,
)

from .access import business_admin_required


class ProxyEvidenceForm(forms.Form):
    proxy_reason = forms.CharField(
        label="本人申請ができない理由", max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    evidence = forms.CharField(
        label="確認資料の名称・確認日・確認方法", max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


def _initial_values(values):
    def local(value):
        return timezone.localtime(datetime.fromisoformat(value)).strftime(DATETIME_FORMAT) if value else None
    return (
        {"clock_in_at": local(values["clock_in_at"]),
         "clock_out_at": local(values["clock_out_at"])},
        [{"started_at": local(item["started_at"]),
          "ended_at": local(item["ended_at"])} for item in values["breaks"]] or [{}],
    )


def _initial(session):
    return _initial_values(current_values(session))


@never_cache
@business_admin_required
def proxy_correction(request, employee_id, year, month, day):
    employee = get_object_or_404(get_user_model(), pk=employee_id)
    try:
        work_day = date(year, month, day)
    except ValueError:
        raise Http404("勤務日が不正です。")
    if employee.is_active:
        messages.error(request, "代理申請は停止中社員だけが対象です。")
        return redirect("management:employee_month", employee_id=employee_id, year=year, month=month)
    if is_month_finalized(employee, work_day):
        messages.error(request, "確定を解除してから代理申請してください。")
        return redirect("management:employee_month", employee_id=employee_id, year=year, month=month)
    session = WorkSession.objects.filter(employee=employee, work_date=work_day).first()

    return_payload = None
    token = request.POST.get("confirm_token") or request.POST.get("return_token")
    if request.method == "POST" and token:
        try:
            payload = signing.loads(token, salt="attendance-proxy-v1", max_age=900)
            if not isinstance(payload, dict) or not {
                "actor_id", "employee_id", "work_day", "expected_version",
                "proposal", "reason", "proxy_reason", "evidence",
            } <= payload.keys() or not isinstance(payload["proposal"], dict):
                raise CorrectionError("確認内容が不正です。最初から入力してください。")
            if (payload["actor_id"] != request.user.pk or payload["employee_id"] != employee.pk
                    or payload["work_day"] != work_day.isoformat()):
                raise CorrectionError("確認内容が一致しません。")
        except (signing.BadSignature, KeyError, CorrectionError) as exc:
            messages.error(request, str(exc))
        else:
            return_payload = payload
            if request.POST.get("confirm_token"):
                try:
                    correction = submit_correction(
                        employee_id=employee.pk, actor_id=request.user.pk,
                        work_day=work_day, expected_version=payload["expected_version"],
                        proposal=payload["proposal"], reason=payload["reason"],
                        proxy_reason=payload["proxy_reason"], evidence=payload["evidence"],
                    )
                except (KeyError, CorrectionError) as exc:
                    messages.error(request, str(exc))
                except SAVE_FAILURE_ERRORS:
                    log_save_failure("proxy_submit", employee_id=employee.pk, work_day=work_day)
                    messages.error(request, UNCONFIRMED_SAVE_MESSAGE)
                else:
                    messages.success(request, "代理申請を受け付けました。")
                    return redirect("management:correction_detail", pk=correction.pk)
    if request.method == "POST" and not token:
        form = CorrectionValuesForm(request.POST)
        evidence_form = ProxyEvidenceForm(request.POST)
        breaks = CorrectionBreakFormSet(request.POST, prefix="breaks")
        if form.is_valid() and evidence_form.is_valid() and breaks.is_valid():
            try:
                proposal = validate_proposal(make_proposal(form, breaks), work_day)
                if proposal == current_values(session):
                    raise CorrectionError("変更内容がありません。")
            except CorrectionError as exc:
                form.add_error(None, str(exc))
            else:
                token = signing.dumps({
                    "actor_id": request.user.pk, "employee_id": employee.pk,
                    "work_day": work_day.isoformat(),
                    "expected_version": session.version if session else 0,
                    "proposal": proposal, "reason": form.cleaned_data["reason"],
                    **evidence_form.cleaned_data,
                }, salt="attendance-proxy-v1")
                return render(request, "management/proxy_confirm.html", {
                    "employee": employee, "work_day": work_day,
                    "target_day": proposal_work_day(proposal, work_day),
                    "current": current_values(session), "proposal": proposal,
                    "reason": form.cleaned_data["reason"],
                    "proxy_reason": evidence_form.cleaned_data["proxy_reason"],
                    "evidence": evidence_form.cleaned_data["evidence"],
                    "confirm_token": token,
                })
    else:
        if return_payload:
            try:
                initial, initial_breaks = _initial_values(return_payload["proposal"])
                initial["reason"] = return_payload["reason"]
            except (KeyError, TypeError, ValueError):
                messages.error(request, "確認内容が不正です。最初から入力してください。")
                return_payload = None
                initial, initial_breaks = _initial(session)
        else:
            initial, initial_breaks = _initial(session)
        form = CorrectionValuesForm(initial=initial)
        evidence_form = ProxyEvidenceForm(initial={
            "proxy_reason": return_payload["proxy_reason"],
            "evidence": return_payload["evidence"],
        } if return_payload else None)
        breaks = CorrectionBreakFormSet(initial=initial_breaks, prefix="breaks")
    return render(request, "management/proxy_form.html", {
        "employee": employee, "work_day": work_day, "form": form,
        "evidence_form": evidence_form, "break_formset": breaks,
    })


@never_cache
@business_admin_required
@require_POST
def proxy_withdraw(request, pk):
    try:
        correction = withdraw_correction(
            employee_id=request.user.pk, request_id=pk,
            reason=request.POST.get("reason", ""),
        )
    except CorrectionError as exc:
        messages.error(request, str(exc))
    except SAVE_FAILURE_ERRORS:
        log_save_failure("proxy_withdraw", request_id=pk)
        messages.error(request, UNCONFIRMED_SAVE_MESSAGE)
    else:
        messages.success(request, "代理申請を取り下げました。")
    return redirect("management:correction_detail", pk=pk)
