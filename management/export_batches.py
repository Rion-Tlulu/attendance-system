"""Coordinated CSV export from frozen monthly closing values."""

import csv
import io
from datetime import datetime

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from attendance.models import MonthlyClosing
from attendance.validation import month_integrity_issues
from auditlog.models import AuditLog
from config.db_errors import SAVE_FAILURE_ERRORS, UNCONFIRMED_SAVE_MESSAGE, log_save_failure

from .access import business_admin_required
from .csv_format import csv_safe
from .models import ExportBatch


def _jst(value):
    return timezone.localtime(datetime.fromisoformat(value)).strftime("%Y-%m-%d %H:%M:%S") if value else ""


def create_export_batch(actor, employees, target_month):
    """Caller holds a transaction; freeze the selected closing versions."""
    ids = [item.pk for item in employees]
    if not ids:
        raise ValueError("対象社員がいません。")
    closings = list(MonthlyClosing.objects.select_for_update().filter(
        employee_id__in=ids, target_month=target_month,
        status=MonthlyClosing.Status.FINALIZED,
    ).order_by("employee_id"))
    if len(closings) != len(ids) or any(
        not item.snapshot or item.snapshot.get("data_version") != item.version
        or item.integrity_check_result.get("data_version") != item.version
        or item.integrity_check_result.get("issue_count") != 0
        for item in closings
    ):
        raise ValueError("現行の確定版がない社員がいます。再照合・再確定してください。")
    snapshots = [item.snapshot for item in closings]
    if any(not snapshot.get("daily") for snapshot in snapshots):
        raise ValueError("対象月に在籍日がない確定版を含むため出力できません。")
    numbers = [item["employee_number"] for item in snapshots]
    if len(numbers) != len(set(numbers)):
        raise ValueError("確定版の社員番号が重複しています。番号訂正後に再確定してください。")
    for employee in employees:
        if month_integrity_issues(employee, target_month):
            raise ValueError(f"{employee.employee_number} の勤務に不整合があります。")
    return ExportBatch.objects.create(
        created_by=actor, target_month=target_month,
        manifest=[{"employee_id": item.employee_id, "closing_id": item.pk,
                   "version": item.version} for item in closings],
    )


def current_snapshots(batch):
    """Reject either file if any member has been reopened or recertified."""
    manifest = batch.manifest
    ids = [item["closing_id"] for item in manifest]
    closings = {
        item.pk: item for item in MonthlyClosing.objects.select_for_update().filter(pk__in=ids)
    }
    snapshots = []
    for item in manifest:
        closing = closings.get(item["closing_id"])
        if (closing is None or closing.status != MonthlyClosing.Status.FINALIZED
                or closing.version != item["version"] or not closing.snapshot
                or closing.snapshot.get("data_version") != closing.version
                or closing.integrity_check_result.get("data_version") != closing.version
                or closing.integrity_check_result.get("issue_count") != 0):
            raise ValueError("出力IDの確定版が変更されました。新しい出力IDで両方を取得してください。")
        if month_integrity_issues(closing.employee, batch.target_month):
            raise ValueError("勤務の不整合があります。再照合・再確定してください。")
        if not closing.snapshot.get("daily"):
            raise ValueError("対象月に在籍日がない確定版は出力できません。")
        snapshots.append(closing.snapshot)
    return snapshots


def write_snapshot_csv(snapshots, output_format):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    if output_format == "daily":
        writer.writerow(["社員番号", "氏名", "部署", "勤務日", "出勤日時", "退勤日時",
                         "休憩秒数", "実働秒数", "記録状態", "確定状態", "データ版"])
        for snapshot in snapshots:
            common = [csv_safe(snapshot[key]) for key in ("employee_number", "name", "department")]
            for day in snapshot["daily"]:
                writer.writerow([
                    *common, day["day"], _jst(day["clock_in_at"]), _jst(day["clock_out_at"]),
                    day["break_seconds"] if day["break_seconds"] is not None else "",
                    day["work_seconds"] if day["work_seconds"] is not None else "",
                    day["record_state"], "確定済み", snapshot["data_version"],
                ])
    else:
        writer.writerow(["社員番号", "氏名", "部署", "対象月", "勤務記録日数", "実働秒数合計",
                         "休憩秒数合計", "未完了件数", "確定日時", "データ版"])
        for snapshot in snapshots:
            common = [csv_safe(snapshot[key]) for key in ("employee_number", "name", "department")]
            writer.writerow([
                *common, snapshot["target_month"], snapshot["recorded_days"],
                snapshot["work_seconds"], snapshot["break_seconds"], snapshot["incomplete_count"],
                _jst(snapshot["finalized_at"]), snapshot["data_version"],
            ])
    return "\ufeff" + output.getvalue()


@never_cache
@business_admin_required
@require_GET
def batch_detail(request, output_id):
    batch = get_object_or_404(ExportBatch, output_id=output_id)
    return render(request, "management/export_batch.html", {"batch": batch})


@never_cache
@business_admin_required
@require_POST
def batch_download(request, output_id, output_format):
    if output_format not in {"daily", "monthly"}:
        return HttpResponseBadRequest("出力種別が不正です。")
    try:
        with transaction.atomic():
            return _batch_download(request, output_id, output_format)
    except SAVE_FAILURE_ERRORS:
        log_save_failure("batch_download", output_id=str(output_id), output_format=output_format)
        batch = get_object_or_404(ExportBatch, output_id=output_id)
        return render(request, "management/export_batch.html", {
            "batch": batch, "error": UNCONFIRMED_SAVE_MESSAGE,
        }, status=503)


def _batch_download(request, output_id, output_format):
    batch = get_object_or_404(ExportBatch.objects.select_for_update(), output_id=output_id)
    try:
        snapshots = current_snapshots(batch)
    except ValueError as exc:
        return render(request, "management/export_batch.html", {
            "batch": batch, "error": str(exc),
        }, status=409)
    response = HttpResponse(write_snapshot_csv(snapshots, output_format), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="attendance_{batch.target_month:%Y%m}_{batch.output_id}_{output_format}.csv"'
    )
    response["Cache-Control"] = "no-store"
    AuditLog.objects.create(
        actor=request.user, action=AuditLog.Action.CSV_EXPORT,
        target_model="ExportBatch", target_id=str(batch.output_id),
        before_data={}, after_data={"downloaded": output_format},
        reason="確定版CSVの取得",
        details={"output_id": str(batch.output_id), "format": output_format,
                 "target_month": batch.target_month.isoformat(), "manifest": batch.manifest},
    )
    return response


@never_cache
@business_admin_required
@require_POST
def single_month_batch(request, employee_id, year, month):
    from datetime import date
    try:
        target_month = date(year, month, 1)
    except ValueError:
        return HttpResponseBadRequest("対象月が不正です。")
    try:
        with transaction.atomic():
            employee = get_object_or_404(
                get_user_model().objects.select_for_update(), pk=employee_id,
            )
            batch = create_export_batch(request.user, [employee], target_month)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    except SAVE_FAILURE_ERRORS:
        log_save_failure("single_month_batch", employee_id=employee_id, month=target_month)
        messages.error(request, UNCONFIRMED_SAVE_MESSAGE)
        return redirect("management:employee_month", employee_id=employee_id, year=year, month=month)
    return redirect("management:batch_detail", output_id=batch.output_id)
