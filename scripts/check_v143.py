"""Read-only audit before and after the v1.4.3 migration."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from django.contrib.auth import get_user_model
from django.db.models import Count

from attendance.models import IncompleteOccurrence, MonthlyClosing, WorkSession
from attendance.validation import employment_dates, month_integrity_issues
from corrections.models import CorrectionRequest


def main():
    Employee = get_user_model()
    duplicates = Employee.objects.values("employee_number").annotate(total=Count("pk")).filter(total__gt=1)
    print("社員番号の重複:", list(duplicates))
    active_admins = Employee.objects.filter(is_active=True, is_business_admin=True).count()
    if active_admins < 2:
        print(f"有効な業務管理者が不足: 現在{active_admins}人、必要2人以上")
    for correction in CorrectionRequest.objects.filter(
        work_session__status=WorkSession.Status.NO_RECORD,
        work_session__version=1, original_version=1,
    ).select_related("work_session").iterator():
        print(f"旧仮勤務の個別確認候補: 申請ID={correction.pk} 勤務ID={correction.work_session_id}")
    unknown_recipients = IncompleteOccurrence.objects.filter(
        recipients_selected=True, recipient_ids=[], ended_at__isnull=True,
    ).count()
    if unknown_recipients:
        print(f"旧未完了通知の送信先要確認: {unknown_recipients}件")
    for employee in Employee.objects.all().iterator():
        hire_date, _ = employment_dates(employee)
        if hire_date is None:
            print(f"入社日未確認: 社員ID={employee.pk} 番号={employee.employee_number}")
        months = {
            work_day.replace(day=1) for work_day in WorkSession.objects.filter(
                employee=employee,
            ).values_list("work_date", flat=True)
        }
        for month in sorted(months):
            for work_day, reason in month_integrity_issues(employee, month):
                print(f"勤務不整合: 社員ID={employee.pk} 月={month:%Y-%m} 日={work_day} 理由={reason}")
    for closing in MonthlyClosing.objects.filter(status=MonthlyClosing.Status.FINALIZED):
        if not closing.snapshot:
            print(f"確定版未構成: 社員ID={closing.employee_id} 月={closing.target_month:%Y-%m}")
    print("読取専用の確認です。旧確定版や社員番号は自動変更していません。")


if __name__ == "__main__":
    main()
