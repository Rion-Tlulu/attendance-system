import uuid

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from attendance.models import (
    ClockEvent,
    MonthlyClosing,
    WorkSession,
)
from auditlog.models import AuditLog
from corrections.models import CorrectionRequest
from corrections.services import current_values


class Phase9Tests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.manager = Employee.objects.create_user(
            employee_number="94001",
            password="ManagerPhase9_2026!",
            first_name="管理",
            last_name="担当",
            is_business_admin=True,
        )

        self.other_manager = Employee.objects.create_user(
            employee_number="94002",
            password="OtherManagerPhase9_2026!",
            first_name="別の",
            last_name="管理者",
            is_business_admin=True,
        )

        self.employee = Employee.objects.create_user(
            employee_number="94003",
            password="EmployeePhase9_2026!",
            first_name="社員",
            last_name="テスト",
        )

        self.day = date(2026, 9, 15)
        self.jst = ZoneInfo("Asia/Tokyo")

        self.work = WorkSession.objects.create(
            employee=self.employee,
            work_date=self.day,
            clock_in_at=self.dt(9),
            clock_out_at=self.dt(18),
            status=WorkSession.Status.COMPLETED,
        )

    def dt(self, hour, minute=0):
        return datetime(
            2026,
            9,
            15,
            hour,
            minute,
            tzinfo=self.jst,
        )

    def create_request(self, work=None):
        work = work or self.work

        proposal = current_values(work)

        proposal["clock_out_at"] = "2026-09-15T18:30:00+09:00"

        return CorrectionRequest.objects.create(
            work_session=work,
            requested_by=work.employee,
            original_version=work.version,
            proposal=proposal,
            reason="退勤時刻を修正するため",
            status=CorrectionRequest.Status.PENDING,
        )

    def test_anonymous_admin_access_redirected(self):
        response = self.client.get(reverse("management:attendance_list"))

        self.assertEqual(response.status_code, 302)

    def test_employee_cannot_open_admin_list(self):
        self.client.force_login(self.employee)

        for name in (
            "management:attendance_list",
            "management:corrections",
            "management:employees",
            "management:audit_history",
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 403)

    def test_staff_flag_alone_is_not_business_admin(self):
        self.employee.is_staff = True
        self.employee.save(update_fields=["is_staff"])

        self.client.force_login(self.employee)

        response = self.client.get(reverse("management:attendance_list"))

        self.assertEqual(response.status_code, 403)

    def test_manager_can_open_attendance_list(self):
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse("management:attendance_list"),
            {"month": "2026-09"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "勤怠一覧")

    def test_manager_can_open_employee_month(self):
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse(
                "management:employee_month",
                args=[self.employee.pk, 2026, 9],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "月次勤怠詳細")

    def test_approve_updates_effective_values(self):
        correction = self.create_request()

        event = ClockEvent.objects.create(
            work_session=self.work,
            kind=ClockEvent.Kind.CLOCK_OUT,
            recorded_at=self.dt(18),
            operation_id=uuid.uuid4(),
        )

        self.client.force_login(self.manager)

        response = self.client.post(
            reverse(
                "management:correction_review",
                args=[correction.pk],
            ),
            {"action": "approve", "return_reason": ""},
        )

        self.assertEqual(response.status_code, 302)

        correction.refresh_from_db()
        self.work.refresh_from_db()
        event.refresh_from_db()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.APPROVED,
        )

        self.assertEqual(
            self.work.clock_out_at,
            self.dt(18, 30),
        )

        # 原打刻は変更されない
        self.assertEqual(event.recorded_at, self.dt(18))

        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.CORRECTION_APPROVE,
            ).exists()
        )

    def test_return_does_not_update_effective_values(self):
        correction = self.create_request()

        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:correction_review",
                args=[correction.pk],
            ),
            {
                "action": "return",
                "return_reason": "申請内容を確認してください。",
            },
        )

        correction.refresh_from_db()
        self.work.refresh_from_db()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.RETURNED,
        )

        self.assertEqual(
            self.work.clock_out_at,
            self.dt(18),
        )

    def test_self_approval_is_blocked(self):
        own_work = WorkSession.objects.create(
            employee=self.manager,
            work_date=self.day,
            clock_in_at=self.dt(9),
            clock_out_at=self.dt(18),
            status=WorkSession.Status.COMPLETED,
        )

        correction = self.create_request(own_work)

        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:correction_review",
                args=[correction.pk],
            ),
            {"action": "approve", "return_reason": ""},
        )

        correction.refresh_from_db()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.PENDING,
        )

    def test_stale_correction_is_blocked(self):
        correction = self.create_request()

        self.work.version += 1
        self.work.save(update_fields=["version"])

        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:correction_review",
                args=[correction.pk],
            ),
            {"action": "approve", "return_reason": ""},
        )

        correction.refresh_from_db()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.PENDING,
        )

    def test_pending_request_blocks_finalization(self):
        self.create_request()

        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:month_finalize",
                args=[self.employee.pk, 2026, 9],
            ),
            {"checked_no_record": "on"},
        )

        self.assertFalse(
            MonthlyClosing.objects.filter(
                employee=self.employee,
                target_month=date(2026, 9, 1),
                status=MonthlyClosing.Status.FINALIZED,
            ).exists()
        )

    def test_manager_cannot_finalize_own_month(self):
        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:month_finalize",
                args=[self.manager.pk, 2026, 9],
            ),
            {"checked_no_record": "on"},
        )

        self.assertFalse(
            MonthlyClosing.objects.filter(
                employee=self.manager,
                target_month=date(2026, 9, 1),
                status=MonthlyClosing.Status.FINALIZED,
            ).exists()
        )

    def test_finalization_requires_confirmation(self):
        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:month_finalize",
                args=[self.employee.pk, 2026, 9],
            ),
            {},
        )

        self.assertFalse(
            MonthlyClosing.objects.filter(
                employee=self.employee,
                target_month=date(2026, 9, 1),
                status=MonthlyClosing.Status.FINALIZED,
            ).exists()
        )

    def test_finalization_and_csv(self):
        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:month_finalize",
                args=[self.employee.pk, 2026, 9],
            ),
            {"checked_no_record": "on"},
        )

        self.assertTrue(
            MonthlyClosing.objects.filter(
                employee=self.employee,
                target_month=date(2026, 9, 1),
                status=MonthlyClosing.Status.FINALIZED,
            ).exists()
        )

        response = self.client.get(
            reverse(
                "management:month_csv",
                args=[self.employee.pk, 2026, 9],
            )
        )

        self.assertEqual(response.status_code, 200)

        # UTF-8 BOM
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))

        # CRLF
        self.assertIn(
            b"\r\n",
            response.content,
        )

    def test_unfinalized_month_csv_is_blocked(self):
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse(
                "management:month_csv",
                args=[self.employee.pk, 2026, 9],
            )
        )

        self.assertEqual(response.status_code, 302)

    def test_regular_employee_cannot_download_csv(self):
        self.client.force_login(self.employee)

        response = self.client.get(
            reverse(
                "management:month_csv",
                args=[self.employee.pk, 2026, 9],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_audit_history_is_admin_only(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("management:audit_history"))

        self.assertEqual(response.status_code, 200)

        self.client.force_login(self.employee)

        response = self.client.get(reverse("management:audit_history"))

        self.assertEqual(response.status_code, 403)

    def test_incomplete_work_blocks_finalization(self):
        """未完了の勤務がある月は確定できない。"""

        work_day = date(2026, 9, 16)

        WorkSession.objects.create(
            employee=self.employee,
            work_date=work_day,
            clock_in_at=datetime(
                2026, 9, 16, 9,
                tzinfo=self.jst,
            ),
            status=WorkSession.Status.WORKING,
        )

        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:month_finalize",
                args=[self.employee.pk, 2026, 9],
            ),
            {"checked_no_record": "on"},
        )

        self.assertFalse(
            MonthlyClosing.objects.filter(
                employee=self.employee,
                target_month=date(2026, 9, 1),
                status=MonthlyClosing.Status.FINALIZED,
            ).exists()
        )

    def test_month_can_be_reopened(self):
        """確定済み月を未確定へ戻せる。"""

        closing = MonthlyClosing.objects.create(
            employee=self.employee,
            target_month=date(2026, 9, 1),
            status=MonthlyClosing.Status.FINALIZED,
            finalized_by=self.manager,
            finalized_at=self.dt(18),
        )

        self.client.force_login(self.manager)

        response = self.client.post(
            reverse(
                "management:month_reopen",
                args=[self.employee.pk, 2026, 9],
            ),
            {
                "reason": "勤務情報を再確認するため",
            },
        )

        self.assertEqual(response.status_code, 302)

        closing.refresh_from_db()

        self.assertNotEqual(
            closing.status,
            MonthlyClosing.Status.FINALIZED,
        )

        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.MONTH_REOPEN,
            ).exists()
        )
