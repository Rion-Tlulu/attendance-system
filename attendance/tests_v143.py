"""Acceptance checks for the v1.4.3 interval and proxy rules."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from attendance.models import WorkSession
from attendance.validation import employment_dates, month_integrity_issues, overlapping_sessions
from corrections.models import CorrectionRequest
from corrections.services import submit_correction, withdraw_correction
from management.services import AdminActionError, review_correction
from management.csv_format import csv_safe
from management.models import EmploymentInfo


JST = ZoneInfo("Asia/Tokyo")


def at(day, hour):
    return datetime(day.year, day.month, day.day, hour, tzinfo=JST)


def proposal(start, end):
    return {"clock_in_at": start.isoformat(), "clock_out_at": end.isoformat(), "breaks": []}


class Version143RulesTests(TestCase):
    def setUp(self):
        Employee = get_user_model()
        self.employee = Employee.objects.create_user(
            employee_number="0007", password="TestPassword_2026!",
            hire_date=date(2024, 1, 1),
        )
        self.first_manager = Employee.objects.create_user(
            employee_number="9001", password="TestPassword_2026!",
            is_business_admin=True,
        )
        self.second_manager = Employee.objects.create_user(
            employee_number="9002", password="TestPassword_2026!",
            is_business_admin=True,
        )

    def test_night_shift_overlap_endpoint_and_zero_hours(self):
        first = WorkSession.objects.create(
            employee=self.employee, work_date=date(2024, 1, 1),
            clock_in_at=at(date(2024, 1, 1), 22),
            clock_out_at=at(date(2024, 1, 2), 7),
            status=WorkSession.Status.COMPLETED,
        )
        self.assertEqual(
            overlapping_sessions(self.employee, at(date(2024, 1, 2), 6), at(date(2024, 1, 2), 15)),
            [first],
        )
        self.assertEqual(
            overlapping_sessions(self.employee, at(date(2024, 1, 2), 7), at(date(2024, 1, 2), 15)),
            [],
        )
        self.assertEqual(
            overlapping_sessions(self.employee, at(date(2024, 1, 2), 6), at(date(2024, 1, 2), 6)),
            [],
        )
        self.assertTrue(month_integrity_issues(self.employee, date(2024, 1, 1)) == [])

    def test_proxy_author_cannot_review_but_can_withdraw(self):
        self.employee.is_active = False
        self.employee.save(update_fields=["is_active"])
        correction = submit_correction(
            employee_id=self.employee.pk, actor_id=self.first_manager.pk,
            work_day=date(2024, 1, 2), expected_version=0,
            proposal=proposal(at(date(2024, 1, 2), 9), at(date(2024, 1, 2), 18)),
            reason="打刻漏れ", proxy_reason="本人は利用停止中",
            evidence="勤務表を2024-01-03に担当者が照合",
        )
        with self.assertRaises(AdminActionError):
            review_correction(
                manager_id=self.first_manager.pk, correction_id=correction.pk, action="approve",
            )
        withdraw_correction(employee_id=self.first_manager.pk, request_id=correction.pk)
        correction.refresh_from_db()
        self.assertEqual(correction.status, CorrectionRequest.Status.WITHDRAWN)

    def test_no_record_request_has_no_original_and_creates_work_only_on_approval(self):
        work_day = date(2024, 1, 5)
        correction = submit_correction(
            employee_id=self.employee.pk, work_day=work_day,
            expected_version=0,
            proposal=proposal(at(work_day, 9), at(work_day, 18)),
            reason="打刻漏れ",
        )
        self.assertIsNone(correction.work_session_id)
        self.assertIsNone(correction.original_version)
        self.assertFalse(WorkSession.objects.filter(
            employee=self.employee, work_date=work_day,
        ).exists())
        review_correction(
            manager_id=self.first_manager.pk, correction_id=correction.pk,
            action="approve",
        )
        correction.refresh_from_db()
        self.assertIsNone(correction.work_session_id)
        self.assertIsNone(correction.original_version)
        self.assertEqual(WorkSession.objects.get(
            employee=self.employee, work_date=work_day,
        ).status, WorkSession.Status.COMPLETED)

    def test_no_record_return_and_followup_keep_old_request(self):
        work_day = date(2024, 1, 6)
        first = submit_correction(
            employee_id=self.employee.pk, work_day=work_day,
            expected_version=0,
            proposal=proposal(at(work_day, 9), at(work_day, 18)),
            reason="打刻漏れ",
        )
        review_correction(
            manager_id=self.first_manager.pk, correction_id=first.pk,
            action="return", return_reason="資料を確認してください",
        )
        self.assertFalse(WorkSession.objects.filter(
            employee=self.employee, work_date=work_day,
        ).exists())

        second = submit_correction(
            employee_id=self.employee.pk, work_day=work_day,
            expected_version=0,
            proposal=proposal(at(work_day, 10), at(work_day, 18)),
            reason="資料を再確認",
        )
        self.assertEqual(second.related_request_id, first.pk)
        withdraw_correction(employee_id=self.employee.pk, request_id=second.pk)
        self.assertFalse(WorkSession.objects.filter(
            employee=self.employee, work_date=work_day,
        ).exists())

    def test_two_active_managers_cannot_be_reduced_by_role_or_deactivation(self):
        self.first_manager.is_business_admin = False
        with self.assertRaises(ValidationError):
            self.first_manager.save(update_fields=["is_business_admin"])
        self.first_manager.refresh_from_db()
        self.first_manager.is_active = False
        with self.assertRaises(ValidationError):
            self.first_manager.save(update_fields=["is_active"])
        self.first_manager.refresh_from_db()
        third = get_user_model().objects.create_user(
            employee_number="9003", password="TestPassword_2026!",
            is_business_admin=True,
        )
        self.first_manager.is_business_admin = False
        self.first_manager.save(update_fields=["is_business_admin"])
        self.assertEqual(get_user_model().objects.filter(
            is_active=True, is_business_admin=True,
        ).count(), 2)
        self.assertTrue(third.is_business_admin)

    def test_partial_update_does_not_use_stale_role_value(self):
        from auditlog.models import AuditLog

        self.first_manager.is_business_admin = False  # stale in-memory value
        self.first_manager.is_active = True
        self.first_manager.save(update_fields=["is_active"])
        self.first_manager.refresh_from_db()
        self.assertTrue(self.first_manager.is_business_admin)
        self.assertFalse(AuditLog.objects.filter(
            action=AuditLog.Action.ROLE_CHANGE,
            target_employee=self.first_manager,
        ).exists())

    def test_approved_date_move_keeps_source_history(self):
        source = WorkSession.objects.create(
            employee=self.employee, work_date=date(2024, 1, 3),
            clock_in_at=at(date(2024, 1, 3), 9),
            clock_out_at=at(date(2024, 1, 3), 18),
            status=WorkSession.Status.COMPLETED,
        )
        correction = submit_correction(
            employee_id=self.employee.pk, work_day=source.work_date,
            expected_version=source.version,
            proposal=proposal(at(date(2024, 1, 4), 9), at(date(2024, 1, 4), 18)),
            reason="勤務日の訂正",
        )
        review_correction(
            manager_id=self.first_manager.pk, correction_id=correction.pk,
            action="approve",
        )
        source.refresh_from_db()
        self.assertEqual(source.status, WorkSession.Status.NO_RECORD)
        self.assertEqual(source.moved_to.work_date, date(2024, 1, 4))
        self.assertEqual(source.moved_to.status, WorkSession.Status.COMPLETED)

    def test_csv_text_round_trip_prefix(self):
        self.assertEqual(csv_safe("0007"), "0007")
        self.assertEqual(csv_safe("=1+2"), "TXT_=1+2")
        self.assertEqual(csv_safe("TXT_営業"), "TXT_TXT_営業")
        self.assertEqual(csv_safe("　＋1"), "TXT_　＋1")
        self.assertEqual(csv_safe(""), "")

    def test_employment_profile_can_clear_legacy_retirement_date(self):
        self.employee.retirement_date = date(2024, 1, 31)
        self.employee.save(update_fields=["retirement_date"])
        EmploymentInfo.objects.create(
            employee=self.employee, hire_date=date(2024, 1, 1), leave_date=None,
        )
        self.assertEqual(employment_dates(self.employee), (date(2024, 1, 1), None))
