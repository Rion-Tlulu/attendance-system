"""v1.4 リリース修正の受入テスト。"""

import csv
from datetime import date, datetime
from io import StringIO
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from attendance.models import MonthlyClosing, WorkSession
from auditlog.models import AuditLog
from management.models import EmploymentInfo
from management.services import finalize_month, reopen_month
from notifications.models import Notification


class ReleaseAcceptanceTests(TestCase):
    def setUp(self):
        Employee = get_user_model()
        self.manager = Employee.objects.create_user(
            employee_number="91001", password="ManagerPass_2026!", is_business_admin=True
        )
        self.employee = Employee.objects.create_user(
            employee_number="91002", password="EmployeePass_2026!",
            first_name="花子", last_name="山田",
        )
        self.client.force_login(self.manager)

    def test_registration_and_reset_are_one_time_and_not_cached(self):
        create = self.client.post(reverse("management:employee_create"), {
            "employee_number": "91003", "first_name": "太郎", "last_name": "佐藤",
            "department": "営業部",
        })
        self.assertEqual(create.status_code, 200)
        self.assertContains(create, "初期パスワード")
        self.assertIn("no-store", create["Cache-Control"])
        created = get_user_model().objects.get(employee_number="91003")
        reset_url = reverse("management:employee_password_reset", args=[created.pk])
        confirm = self.client.get(reset_url)
        self.assertEqual(confirm.status_code, 200)
        self.assertContains(confirm, "再発行の確認")
        ticket = confirm.context["ticket"]
        reset = self.client.post(reset_url, {"ticket": ticket, "confirm": "yes"})
        self.assertEqual(reset.status_code, 200)
        self.assertContains(reset, "初期パスワード再発行が完了")
        self.assertIn("no-store", reset["Cache-Control"])
        replay = self.client.post(reset_url, {"ticket": ticket, "confirm": "yes"})
        self.assertEqual(replay.status_code, 400)
        self.assertNotIn("初期パスワード再発行が完了", replay.content.decode())

    def test_month_notifications_for_finalize_reopen_refinalize(self):
        month = date(2026, 9, 1)
        args = dict(manager_id=self.manager.pk, employee_id=self.employee.pk,
                    target_month=month)
        finalize_month(**args, checked_no_record=True)
        reopen_month(**args, reason="再確認が必要")
        finalize_month(**args, checked_no_record=True)
        self.assertEqual(list(Notification.objects.filter(recipient=self.employee)
                         .order_by("created_at", "pk").values_list("kind", flat=True)), [
            Notification.Kind.MONTH_FINALIZED,
            Notification.Kind.MONTH_REOPENED,
            Notification.Kind.MONTH_FINALIZED,
        ])

    def test_csv_schema_values_and_employment_period(self):
        month = date(2026, 9, 1)
        jst = ZoneInfo("Asia/Tokyo")
        WorkSession.objects.create(
            employee=self.employee, work_date=date(2026, 9, 15),
            clock_in_at=datetime(2026, 9, 15, 9, tzinfo=jst),
            clock_out_at=datetime(2026, 9, 15, 18, tzinfo=jst),
            status=WorkSession.Status.COMPLETED,
        )
        EmploymentInfo.objects.create(
            employee=self.employee, department="営業部",
            hire_date=date(2026, 9, 15), leave_date=date(2026, 9, 20),
        )
        MonthlyClosing.objects.create(
            employee=self.employee, target_month=month,
            status=MonthlyClosing.Status.FINALIZED,
            finalized_by=self.manager, finalized_at=timezone.now(),
        )
        base = {"month": "2026-09", "scope": "employee", "department": "",
                "employee_number": self.employee.employee_number, "mode": "download"}
        daily = self.client.post(reverse("management:bulk_export"),
                                 {**base, "output_format": "daily"})
        self.assertEqual(daily.status_code, 200)
        self.assertTrue(daily.content.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", daily.content)
        daily_rows = list(csv.reader(StringIO(daily.content.decode("utf-8-sig"))))
        self.assertEqual(daily_rows[0], ["社員番号", "氏名", "部署", "勤務日",
            "出勤日時", "退勤日時", "休憩秒数", "実働秒数", "記録状態", "確定状態", "データ版"])
        self.assertEqual(len(daily_rows), 7)
        self.assertEqual(daily_rows[1][4:6], ["2026-09-15 09:00:00", "2026-09-15 18:00:00"])
        self.assertEqual(daily_rows[1][7], "32400")
        monthly = self.client.post(reverse("management:bulk_export"),
                                   {**base, "output_format": "monthly"})
        self.assertEqual(monthly.status_code, 200)
        monthly_rows = list(csv.reader(StringIO(monthly.content.decode("utf-8-sig"))))
        self.assertEqual(monthly_rows[0], ["社員番号", "氏名", "部署", "対象月", "勤務記録日数",
            "実働秒数", "休憩秒数", "未完了件数", "確定日時", "データ版"])
        self.assertEqual(monthly_rows[1][4:8], ["1", "32400", "0", "0"])

    def test_role_change_and_login_failure_are_audited(self):
        self.employee.is_business_admin = True
        self.employee.save(update_fields=["is_business_admin"])
        self.assertTrue(AuditLog.objects.filter(
            action=AuditLog.Action.ROLE_CHANGE, target_employee=self.employee,
        ).exists())
        self.client.logout()
        self.client.post(reverse("accounts:login"), {
            "username": self.employee.employee_number, "password": "incorrect-password",
        })
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.AUTH_FAILURE).exists())
