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

from corrections.views import (
    _attach_break_befores, _break_initial_with_operations, _display_proposal, _operation,
)

from .access import business_admin_required


class ProxyEvidenceForm(forms.Form):
    """代理申請の追加理由と、確認した資料の名称・確認日・確認方法（画面 24）。

    資料の3項目は保存時に1つの確認情報（evidence）にまとめ、各項目の合計を1000文字以内に収める。
    """

    proxy_reason = forms.CharField(
        label="本人申請ができない理由", max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    evidence_name = forms.CharField(label="資料名", max_length=300)
    evidence_date = forms.DateField(
        label="確認日",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    evidence_method = forms.CharField(label="確認方法", max_length=300)

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get("evidence_name") or "").strip()
        checked_on = cleaned.get("evidence_date")
        method = (cleaned.get("evidence_method") or "").strip()
        if name and checked_on and method:
            cleaned["evidence"] = (
                f"資料名：{name}／確認日：{checked_on:%Y-%m-%d}／確認方法：{method}"
            )
        return cleaned

    def payload(self):
        """確認画面の署名付きトークンに入れる値（JSONに変換できる形）。"""
        return {
            "proxy_reason": self.cleaned_data["proxy_reason"],
            "evidence": self.cleaned_data["evidence"],
            "evidence_name": self.cleaned_data["evidence_name"],
            "evidence_date": self.cleaned_data["evidence_date"].isoformat(),
            "evidence_method": self.cleaned_data["evidence_method"],
        }


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


def _initial_with_operations(session, proposal=None):
    """画面 24：操作（変更しない／変更／追加／取消）付きの初期値を作る。"""
    current = current_values(session)
    proposal = proposal or current
    shown = {
        "clock_in_at": proposal.get("clock_in_at") or current.get("clock_in_at"),
        "clock_out_at": proposal.get("clock_out_at") or current.get("clock_out_at"),
        "breaks": [],
    }
    initial, _ = _initial_values(shown)
    initial["clock_in_op"] = _operation(current.get("clock_in_at"), proposal.get("clock_in_at"))
    initial["clock_out_op"] = _operation(current.get("clock_out_at"), proposal.get("clock_out_at"))
    breaks = _break_initial_with_operations(current.get("breaks", []), proposal.get("breaks", []))
    return initial, breaks


def _render_form(request, employee, work_day, session, form, evidence_form, breaks):
    _attach_break_befores(breaks, session)
    return render(request, "management/proxy_form.html", {
        "employee": employee, "work_day": work_day, "form": form,
        "evidence_form": evidence_form, "break_formset": breaks,
        "current_display": _display_proposal(current_values(session)),
    })


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
                proposal = validate_proposal(make_proposal(form, breaks, current_values(session)), work_day)
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
                    **evidence_form.payload(),
                }, salt="attendance-proxy-v1")
                return render(request, "management/proxy_confirm.html", {
                    "employee": employee, "work_day": work_day,
                    "target_day": proposal_work_day(proposal, work_day),
                    "current": current_values(session), "proposal": proposal,
                    "reason": form.cleaned_data["reason"],
                    "proxy_reason": evidence_form.cleaned_data["proxy_reason"],
                    "evidence": evidence_form.cleaned_data["evidence"],
                    "evidence_name": evidence_form.cleaned_data["evidence_name"],
                    "evidence_date": evidence_form.cleaned_data["evidence_date"],
                    "evidence_method": evidence_form.cleaned_data["evidence_method"],
                    "confirm_token": token,
                })
    else:
        if return_payload:
            try:
                initial, initial_breaks = _initial_with_operations(session, return_payload["proposal"])
                initial["reason"] = return_payload["reason"]
            except (KeyError, TypeError, ValueError, AttributeError):
                messages.error(request, "確認内容が不正です。最初から入力してください。")
                return_payload = None
                initial, initial_breaks = _initial_with_operations(session)
        else:
            initial, initial_breaks = _initial_with_operations(session)
        form = CorrectionValuesForm(initial=initial)
        evidence_form = ProxyEvidenceForm(initial={
            "proxy_reason": return_payload.get("proxy_reason", ""),
            "evidence_name": return_payload.get("evidence_name", ""),
            "evidence_date": return_payload.get("evidence_date", ""),
            "evidence_method": return_payload.get("evidence_method", ""),
        } if return_payload else None)
        breaks = CorrectionBreakFormSet(initial=initial_breaks, prefix="breaks")
    return _render_form(request, employee, work_day, session, form, evidence_form, breaks)


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
