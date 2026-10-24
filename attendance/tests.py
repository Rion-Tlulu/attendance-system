
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from attendance.models import (
    WorkSession,
    BreakInterval,
    MonthlyClosing,
)
from corrections.models import CorrectionRequest


class Phase2ModelTests(TestCase):
    """Phase 2のモデル基本テスト。"""

    def setUp(self):
        Employee = get_user_model()

        self.employee = Employee.objects.create_user(
            employee_number="00124",
            password="TestOnly_2026!Password",
            last_name="山田",
            first_name="花子",
            department="営業部",
            hire_date=date(2026, 4, 1),
        )

        jst = ZoneInfo("Asia/Tokyo")

        self.clock_in = datetime(
            2026, 10, 15, 9, 0,
            tzinfo=jst,
        )

        self.clock_out = datetime(
            2026, 10, 15, 18, 0,
            tzinfo=jst,
        )

        self.session = WorkSession.objects.create(
            employee=self.employee,
            work_date=date(2026, 10, 15),
            clock_in_at=self.clock_in,
            clock_out_at=self.clock_out,
            status=WorkSession.Status.COMPLETED,
        )

    def test_employee_number(self):
        self.assertEqual(
            self.employee.employee_number,
            "00124",
        )

        self.assertEqual(
            self.employee.display_name,
            "山田 花子",
        )

    def test_password_is_hashed(self):
        self.assertNotEqual(
            self.employee.password,
            "TestOnly_2026!Password",
        )

        self.assertTrue(
            self.employee.check_password(
                "TestOnly_2026!Password"
            )
        )

    def test_work_duration(self):
        jst = ZoneInfo("Asia/Tokyo")

        break_start = datetime(
            2026, 10, 15, 12, 0,
            tzinfo=jst,
        )

        break_end = datetime(
            2026, 10, 15, 13, 0,
            tzinfo=jst,
        )

        rest = BreakInterval.objects.create(
            work_session=self.session,
            started_at=break_start,
            ended_at=break_end,
        )

        work_seconds = (
            self.session.clock_out_at
            - self.session.clock_in_at
        ).total_seconds()

        break_seconds = (
            rest.ended_at
            - rest.started_at
        ).total_seconds()

        actual_seconds = work_seconds - break_seconds

        self.assertEqual(
            actual_seconds,
            8 * 60 * 60,
        )

    def test_duplicate_work_date(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WorkSession.objects.create(
                    employee=self.employee,
                    work_date=date(2026, 10, 15),
                )

    def test_duplicate_pending_correction(self):
        CorrectionRequest.objects.create(
            work_session=self.session,
            requested_by=self.employee,
            original_version=self.session.version,
            proposal={},
            reason="テスト申請1",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CorrectionRequest.objects.create(
                    work_session=self.session,
                    requested_by=self.employee,
                    original_version=self.session.version,
                    proposal={},
                    reason="テスト申請2",
                )

    def test_self_approval_validation(self):
        request = CorrectionRequest(
            work_session=self.session,
            requested_by=self.employee,
            reviewed_by=self.employee,
            original_version=self.session.version,
            proposal={},
            reason="テスト申請",
        )

        with self.assertRaises(ValidationError):
            request.full_clean()

    def test_month_start_validation(self):
        closing = MonthlyClosing(
            employee=self.employee,
            target_month=date(2026, 10, 2),
        )

        with self.assertRaises(ValidationError):
            closing.full_clean()
