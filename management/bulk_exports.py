"""
管理者用・確定済み勤怠の一括CSV出力。

対象範囲:
- 全社員
- 部署別
- 社員指定

出力形式:
- 日次明細
- 月次集計

未確定の社員が含まれる場合は、
一括CSV出力を拒否する。
"""

import csv
from calendar import monthrange
from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from attendance.models import MonthlyClosing, WorkSession
from attendance.reporting import build_monthly_report
from attendance.validation import employed_during_month, month_integrity_issues
from auditlog.models import AuditLog
from config.db_errors import SAVE_FAILURE_ERRORS, UNCONFIRMED_SAVE_MESSAGE, log_save_failure
from django.utils import timezone

from .access import business_admin_required
from .csv_format import csv_safe
from .export_batches import create_export_batch
from .models import EmploymentInfo

Employee = get_user_model()

# 一度の出力で扱う最大社員数
MAX_EXPORT_EMPLOYEES = 500


# ============================================
# 1. CSVの安全対策
# ============================================


def csv_datetime(value):
    """日時を日本時間の給与連携形式へ変換する。"""
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S") if value else ""


# ============================================
# 2. 月次レポートの値を取得する
# ============================================


def report_value(record, field_name):
    """
    月次レポートがオブジェクトまたは辞書の場合に
    指定した値を取得する。

    フィールドが存在しない場合は例外にする。
    集計値を誤って0として出力しないため。
    """

    if isinstance(record, dict):
        return record[field_name]

    return getattr(record, field_name)


# ============================================
# 3. 出力条件フォーム
# ============================================


class BulkExportForm(forms.Form):

    month = forms.RegexField(
        label="対象月",
        regex=r"^\d{4}-(0[1-9]|1[0-2])$",
        widget=forms.TextInput(
            attrs={
                "type": "month",
            }
        ),
    )

    scope = forms.ChoiceField(
        label="対象社員",
        choices=[
            ("all", "全社員"),
            ("department", "部署別"),
            ("employee", "社員を指定"),
        ],
        widget=forms.RadioSelect,
    )

    department = forms.ChoiceField(
        label="部署",
        required=False,
    )

    employee_number = forms.CharField(
        label="社員番号",
        max_length=30,
        required=False,
    )

    output_format = forms.ChoiceField(
        label="出力形式",
        choices=[
            ("daily", "日次明細CSV"),
            ("monthly", "月次集計CSV"),
        ],
        widget=forms.RadioSelect,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 実際に登録されている部署から選択肢を生成
        departments = (
            EmploymentInfo.objects.exclude(department="")
            .order_by("department")
            .values_list(
                "department",
                flat=True,
            )
            .distinct()
        )

        self.fields["department"].choices = [
            ("", "部署を選択してください"),
            *[(department, department) for department in departments],
        ]

    def clean_month(self):
        value = self.cleaned_data["month"]

        try:
            date.fromisoformat(value + "-01")
        except ValueError as exc:
            raise forms.ValidationError("正しい対象月を入力してください。") from exc

        return value

    def clean(self):
        cleaned_data = super().clean()

        scope = cleaned_data.get("scope")

        if scope == "department":
            if not cleaned_data.get("department"):
                self.add_error(
                    "department",
                    "対象部署を選択してください。",
                )

        if scope == "employee":
            employee_number = (cleaned_data.get("employee_number") or "").strip()

            if not employee_number:
                self.add_error(
                    "employee_number",
                    "社員番号を入力してください。",
                )

        return cleaned_data


# ============================================
# 4. 対象社員の取得
# ============================================


def select_employees(data):
    """
    フォーム条件に合う社員を取得する。

    退職・利用停止した社員の過去の勤怠も
    出力対象になり得るため、
    is_active=Trueで限定しない。
    """

    queryset = Employee.objects.select_related("employement_info").filter(
        is_staff=False, is_superuser=False,
    )

    scope = data["scope"]

    if scope == "department":
        queryset = queryset.filter(employement_info__department=data["department"])

    elif scope == "employee":
        employee_number = data["employee_number"].strip()

        queryset = queryset.filter(employee_number=employee_number)

    # 在籍月で絞り込む前に件数制限すると、先頭の対象外社員によって
    # 後続の対象社員が欠落するため、ここでは全候補を返す。
    return list(queryset.order_by("pk"))


# ============================================
# 5. 月次確定状態の確認
# ============================================


def closing_status(employees, target_month):
    """
    対象月が確定済みの社員IDを取得する。

    対応するデータベースでは、
    確定レコードをトランザクション中にロックする。
    """

    employee_ids = [employee.pk for employee in employees]

    return set(
        MonthlyClosing.objects.select_for_update()
        .filter(
            employee_id__in=employee_ids,
            target_month=target_month,
            status=(MonthlyClosing.Status.FINALIZED),
        )
        .values_list(
            "employee_id",
            flat=True,
        )
    )


# ============================================
# 6. CSV書き込み
# ============================================


def write_csv(
    response,
    employees,
    target_month,
    output_format,
):
    """
    対象社員の月次レポートからCSVを生成する。

    既存の勤怠集計ロジックを再利用するため、
    この関数では勤務時間を独自計算しない。
    """

    # Excelで文字コードを判定しやすくする
    response.write("\ufeff")

    writer = csv.writer(
        response,
        lineterminator="\r\n",
    )

    if output_format == "daily":

        writer.writerow(
            [
                "社員番号",
                "氏名",
                "部署",
                "勤務日",
                "出勤日時",
                "退勤日時",
                "休憩秒数",
                "実働秒数",
                "記録状態",
                "確定状態",
                "データ版",
            ]
        )

    else:

        writer.writerow(
            [
                "社員番号",
                "氏名",
                "部署",
                "対象月",
                "勤務記録日数",
                "実働秒数合計",
                "休憩秒数合計",
                "未完了件数",
                "確定日時",
                "データ版",
            ]
        )

    row_count = 0

    for employee in employees:

        # Phase 6以降の月次集計を再利用
        report = build_monthly_report(
            employee,
            target_month,
        )

        # 部署未登録の社員にも対応
        employment = getattr(
            employee,
            "employement_info",
            None,
        )

        department = employment.department if employment is not None else ""

        common_columns = [
            csv_safe(employee.employee_number),
            csv_safe(employee.get_full_name()),
            csv_safe(department),
        ]
        closing = MonthlyClosing.objects.get(employee=employee, target_month=target_month)

        # ------------------------------
        # 月次集計CSV
        # ------------------------------

        if output_format == "monthly":

            work_seconds = report_value(
                report,
                "total_work_seconds",
            )

            break_seconds = report_value(
                report,
                "total_break_seconds",
            )

            writer.writerow(
                [
                    *common_columns,
                    target_month.strftime("%Y-%m"),
                    sum(row.record_key != "no_record" for row in report.rows),
                    work_seconds,
                    break_seconds,
                    report.incomplete_count,
                    csv_datetime(closing.finalized_at),
                    closing.version,
                ]
            )

            row_count += 1

        # ------------------------------
        # 日次明細CSV
        # ------------------------------

        else:

            rows = report_value(
                report,
                "rows",
            )

            ordered_rows = sorted(
                rows,
                key=lambda item: report_value(
                    item,
                    "day",
                ),
            )
            sessions_by_day = {
                session.work_date: session for session in WorkSession.objects.filter(
                    employee=employee,
                    work_date__year=target_month.year,
                    work_date__month=target_month.month,
                )
            }

            for row in ordered_rows:

                work_day = report_value(
                    row,
                    "day",
                )

                if isinstance(work_day, date):
                    day_text = work_day.isoformat()
                else:
                    day_text = str(work_day)

                hire_date = (employment.hire_date if employment else None) or employee.hire_date
                leave_date = (employment.leave_date if employment else None) or employee.retirement_date
                if (hire_date and work_day < hire_date) or (leave_date and work_day > leave_date):
                    continue
                session = sessions_by_day.get(work_day)

                writer.writerow(
                    [
                        *common_columns,
                        day_text,
                        csv_datetime(session.clock_in_at) if session else "",
                        csv_datetime(session.clock_out_at) if session else "",
                        row.break_seconds if row.break_seconds is not None else "",
                        row.work_seconds if row.work_seconds is not None else "",
                        csv_safe(
                            report_value(
                                row,
                                "record_label",
                            )
                        ),
                        csv_safe(
                            report_value(
                                row,
                                "closing_label",
                            )
                        ),
                        session.version if session else "",
                    ]
                )

                row_count += 1

    return row_count


# ============================================
# 7. エラー時のフォーム表示
# ============================================


def render_export_form(
    request,
    form,
    *,
    summary=None,
    status=200,
):
    """
    同じテンプレートに戻して入力内容を保持する。
    """

    context = {
        "form": form,
    }

    if summary is not None:
        context["summary"] = summary

    return render(
        request,
        "management/bulk_export.html",
        context,
        status=status,
    )


# ============================================
# 8. CSV出力ビュー
# ============================================


@never_cache
@business_admin_required
@require_http_methods(["GET", "POST"])
def bulk_export(request):
    """
    管理者用の一括CSV出力画面。

    GET:
        出力条件フォームを表示。

    POST / preview:
        対象社員と確定状況を確認。

    POST / download:
        全対象社員が確定済みの場合のみ
        CSVを生成して返す。
    """

    if request.method == "GET":
        return render_export_form(
            request,
            BulkExportForm(initial={
                "month": request.GET.get("month") or timezone.localdate().strftime("%Y-%m"),
                "scope": request.GET.get("scope") or "all",
                "employee_number": request.GET.get("employee_number") or "",
            }),
        )

    try:
        return process_bulk_export(request)
    except SAVE_FAILURE_ERRORS:
        # 出力IDの発行はロールバック済み。成功と表示せず、再操作を案内する。
        log_save_failure("bulk_export")
        form = BulkExportForm(request.POST)
        form.is_valid()
        form.add_error(None, UNCONFIRMED_SAVE_MESSAGE)
        return render_export_form(request, form, status=503)


@transaction.atomic
def process_bulk_export(request):
    """
    出力判定からCSV作成・監査記録までを
    トランザクション内で実施する。
    """

    form = BulkExportForm(request.POST)

    if not form.is_valid():
        return render_export_form(
            request,
            form,
            status=400,
        )

    data = form.cleaned_data

    target_month = date.fromisoformat(data["month"] + "-01")

    candidates = select_employees(data)
    closings_by_employee = {
        item.employee_id: item for item in MonthlyClosing.objects.filter(
            employee_id__in=[employee.pk for employee in candidates],
            target_month=target_month,
        )
    }
    employees = []
    for employee in candidates:
        closing = closings_by_employee.get(employee.pk)
        if closing and closing.status == MonthlyClosing.Status.FINALIZED and closing.snapshot:
            hire = date.fromisoformat(closing.snapshot["hire_date"]) if closing.snapshot.get("hire_date") else None
            leave = date.fromisoformat(closing.snapshot["leave_date"]) if closing.snapshot.get("leave_date") else None
            last_day = date(target_month.year, target_month.month, 1)
            last_day = last_day.replace(day=monthrange(target_month.year, target_month.month)[1])
            eligible = (hire is None or hire <= last_day) and (leave is None or leave >= target_month)
        else:
            eligible = employed_during_month(employee, target_month)
        if eligible:
            employees.append(employee)

    # 対象社員が存在するか
    if not employees:
        form.add_error(
            None,
            "対象社員が見つかりません。",
        )

    # 出力対象件数の上限
    elif len(employees) > MAX_EXPORT_EMPLOYEES:
        form.add_error(
            None,
            "対象社員が500人を超えています。" "対象範囲を絞ってください。",
        )

    if form.errors:
        return render_export_form(
            request,
            form,
            status=400,
        )

    finalized_ids = closing_status(
        employees,
        target_month,
    )

    not_finalized = [
        employee for employee in employees if employee.pk not in finalized_ids
    ]

    summary = {
        "total_count": len(employees),
        "finalized_count": len(finalized_ids),
        "unfinalized_count": len(not_finalized),
    }

    mode = request.POST.get("mode")

    # ------------------------------
    # 対象確認
    # ------------------------------

    if mode == "preview":

        return render_export_form(
            request,
            form,
            summary=summary,
        )

    # ------------------------------
    # ダウンロード
    # ------------------------------

    if mode not in {"download", "create"}:
        form.add_error(
            None,
            "操作を選択してください。",
        )

    # 未確定の社員が含まれる場合は拒否
    if not_finalized:
        form.add_error(
            None,
            "対象社員に未確定の勤怠があります。" "すべて確定してから出力してください。",
        )

    invalid = [
        employee.employee_number for employee in employees
        if month_integrity_issues(employee, target_month)
    ]
    if invalid:
        form.add_error(
            None,
            "勤務の不整合がある社員は出力できません: " + ", ".join(invalid[:10]),
        )

    if form.errors:
        return render_export_form(
            request,
            form,
            summary=summary,
            status=400,
        )

    try:
        batch = create_export_batch(request.user, employees, target_month)
    except ValueError as exc:
        form.add_error(None, str(exc))
        return render_export_form(request, form, summary=summary, status=400)
    return redirect("management:batch_detail", output_id=batch.output_id)
