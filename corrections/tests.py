from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from attendance.models import (
    BreakInterval,
    MonthlyClosing,
    WorkSession,
)
from auditlog.models import AuditLog
from .models import CorrectionRequest
from .services import (
    CorrectionError,
    submit_correction,
)


class CorrectionFlowTests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.employee = Employee.objects.create_user(
            employee_number="82001",
            password="CorrectionTest_2026!",
            first_name="花子",
            last_name="山田",
        )

        self.other = Employee.objects.create_user(
            employee_number="82002",
            password="OtherCorrection_2026!",
            first_name="太郎",
            last_name="佐藤",
        )

        self.day = date(2026, 10, 15)
        self.jst = ZoneInfo("Asia/Tokyo")

        self.session = WorkSession.objects.create(
            employee=self.employee,
            work_date=self.day,
            clock_in_at=self.dt(self.day, 9),
            clock_out_at=self.dt(self.day, 18),
            status=WorkSession.Status.COMPLETED,
        )

        BreakInterval.objects.create(
            work_session=self.session,
            started_at=self.dt(self.day, 12),
            ended_at=self.dt(self.day, 13),
        )

        self.client.force_login(self.employee)

    def dt(self, day, hour, minute=0):
        return datetime(
            day.year,
            day.month,
            day.day,
            hour,
            minute,
            tzinfo=self.jst,
        )

    def url(self, day=None):
        day = day or self.day

        return reverse(
            "corrections:create",
            args=[
                day.year,
                day.month,
                day.day,
            ],
        )

    def form_data(
        self,
        day=None,
        *,
        clock_out_hour=18,
        clock_out_minute=30,
        include_break=True,
    ):
        day = day or self.day

        data = {
            "clock_in_at": (f"{day.isoformat()}T09:00:00"),
            "clock_out_at": (
                f"{day.isoformat()}T"
                f"{clock_out_hour:02d}:"
                f"{clock_out_minute:02d}:00"
            ),
            "reason": "打刻時刻を修正するため",
            "breaks-TOTAL_FORMS": "1" if include_break else "0",
            "breaks-INITIAL_FORMS": "0",
            "breaks-MIN_NUM_FORMS": "0",
            "breaks-MAX_NUM_FORMS": "20",
        }

        if include_break:
            data.update(
                {
                    "breaks-0-started_at": (f"{day.isoformat()}T12:00:00"),
                    "breaks-0-ended_at": (f"{day.isoformat()}T13:00:00"),
                }
            )

        return data

    def preview(self, day=None, **kwargs):
        day = day or self.day

        return self.client.post(
            self.url(day),
            self.form_data(day, **kwargs),
        )

    def confirm(self, preview_response, day=None):
        day = day or self.day

        token = preview_response.context["confirm_token"]

        return self.client.post(
            self.url(day),
            {"confirm_token": token},
        )

    def test_input_page_opens(self):
        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "勤怠修正申請",
        )

    def test_preview_does_not_save(self):
        response = self.preview()

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "申請内容の確認",
        )

        self.assertEqual(
            CorrectionRequest.objects.count(),
            0,
        )

        self.session.refresh_from_db()

        self.assertEqual(
            self.session.clock_out_at,
            self.dt(self.day, 18),
        )

    def test_return_from_confirmation_preserves_times_breaks_and_reason(self):
        data = self.form_data()
        preview = self.client.post(self.url(), data)
        self.assertContains(preview, "修正前の有効値")
        token = preview.context["confirm_token"]
        response = self.client.post(self.url(), {"confirm_token": token, "back": "1"})
        self.assertTemplateUsed(response, "corrections/form.html")
        self.assertEqual(response.context["form"]["reason"].value(), data["reason"])
        self.assertEqual(response.context["form"]["clock_out_at"].value(), data["clock_out_at"])
        self.assertEqual(response.context["break_formset"].forms[0]["started_at"].value(), data["breaks-0-started_at"])
        self.assertFalse(CorrectionRequest.objects.exists())
        confirmed = self.client.post(self.url(), {"confirm_token": token})
        self.assertEqual(confirmed.status_code, 302)
        self.assertEqual(CorrectionRequest.objects.count(), 1)

    def test_confirm_creates_pending_request(self):
        preview = self.preview()
        response = self.confirm(preview)

        self.assertEqual(response.status_code, 302)

        correction = CorrectionRequest.objects.get()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.PENDING,
        )

        self.assertEqual(
            correction.original_version,
            self.session.version,
        )

        self.session.refresh_from_db()

        # 申請だけでは有効値を変更しない
        self.assertEqual(
            self.session.clock_out_at,
            self.dt(self.day, 18),
        )

        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.CORRECTION_SUBMIT,
            ).exists()
        )

    def test_no_record_day_can_be_requested(self):
        target_day = date(2026, 10, 14)

        preview = self.preview(
            target_day,
            include_break=False,
        )

        # 確認段階では仮勤務も作らない
        self.assertFalse(
            WorkSession.objects.filter(
                employee=self.employee,
                work_date=target_day,
            ).exists()
        )

        self.confirm(preview, target_day)

        # 申請中も勤務を作らず、社員と勤務日で識別する。
        self.assertFalse(WorkSession.objects.filter(
            employee=self.employee, work_date=target_day,
        ).exists())
        correction = CorrectionRequest.objects.get(
            employee=self.employee, work_date=target_day,
            status=CorrectionRequest.Status.PENDING,
        )
        self.assertIsNone(correction.work_session_id)
        self.assertIsNone(correction.original_version)

    def test_future_datetime_rejected(self):
        data = self.form_data()

        data["clock_out_at"] = "2099-01-01T18:00:00"

        response = self.client.post(
            self.url(),
            data,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "未来の日時",
        )

        self.assertEqual(
            CorrectionRequest.objects.count(),
            0,
        )

    def test_overlapping_breaks_rejected(self):
        data = self.form_data()

        data["breaks-TOTAL_FORMS"] = "2"

        data.update(
            {
                "breaks-1-started_at": ("2026-10-15T12:30:00"),
                "breaks-1-ended_at": ("2026-10-15T13:30:00"),
            }
        )

        response = self.client.post(
            self.url(),
            data,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "重複しています",
        )

        self.assertFalse(CorrectionRequest.objects.exists())

    def test_cannot_submit_same_values(self):
        response = self.preview(
            clock_out_hour=18,
            clock_out_minute=0,
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "変更内容がありません",
        )

        self.assertFalse(CorrectionRequest.objects.exists())

    def test_pending_request_blocks_second(self):
        preview = self.preview()
        self.confirm(preview)

        response = self.client.get(self.url())

        self.assertRedirects(
            response,
            reverse(
                "corrections:detail",
                args=[CorrectionRequest.objects.get().pk],
            ),
        )

        self.assertEqual(
            CorrectionRequest.objects.count(),
            1,
        )

    def test_stale_version_rejected(self):
        preview = self.preview()

        self.session.version += 1
        self.session.save(update_fields=["version"])

        response = self.confirm(preview)

        self.assertRedirects(
            response,
            self.url(),
        )

        self.assertFalse(CorrectionRequest.objects.exists())

    def test_tampered_token_rejected(self):
        preview = self.preview()

        token = preview.context["confirm_token"]

        response = self.client.post(
            self.url(),
            {
                "confirm_token": token + "modified",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.assertFalse(CorrectionRequest.objects.exists())

    def test_withdraw_request(self):
        preview = self.preview()
        self.confirm(preview)

        correction = CorrectionRequest.objects.get()

        response = self.client.post(
            reverse(
                "corrections:withdraw",
                args=[correction.pk],
            ),
        )

        self.assertEqual(response.status_code, 302)

        correction.refresh_from_db()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.WITHDRAWN,
        )

        self.assertIsNotNone(correction.withdrawn_at)

        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.CORRECTION_WITHDRAW,
            ).exists()
        )

    def test_resubmit_after_withdraw(self):
        first_preview = self.preview()
        self.confirm(first_preview)

        first = CorrectionRequest.objects.get()

        self.client.post(
            reverse(
                "corrections:withdraw",
                args=[first.pk],
            )
        )

        second_preview = self.preview(
            clock_out_hour=18,
            clock_out_minute=45,
        )
        self.confirm(second_preview)

        self.assertEqual(
            CorrectionRequest.objects.count(),
            2,
        )

        self.assertEqual(
            CorrectionRequest.objects.filter(
                status=CorrectionRequest.Status.PENDING,
            ).count(),
            1,
        )

    def test_finalized_month_blocks_new_request(self):
        MonthlyClosing.objects.create(
            employee=self.employee,
            target_month=date(2026, 10, 1),
            status=MonthlyClosing.Status.FINALIZED,
            finalized_by=self.other,
            finalized_at=timezone.now(),
        )

        response = self.client.get(self.url())

        self.assertRedirects(
            response,
            reverse(
                "attendance:daily",
                args=[2026, 10, 15],
            ),
        )

    def test_cannot_view_other_person_request(self):
        other_session = WorkSession.objects.create(
            employee=self.other,
            work_date=self.day,
            clock_in_at=self.dt(self.day, 9),
            clock_out_at=self.dt(self.day, 18),
            status=WorkSession.Status.COMPLETED,
        )

        correction = CorrectionRequest.objects.create(
            work_session=other_session,
            requested_by=self.other,
            original_version=other_session.version,
            proposal={},
            reason="他社員のテスト",
        )

        response = self.client.get(
            reverse(
                "corrections:detail",
                args=[correction.pk],
            ),
        )

        self.assertEqual(response.status_code, 404)

    def test_anonymous_user_cannot_open_form(self):
        self.client.logout()

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 302)


# v1.4.3 申請・移行の回帰試験

"""Legacy no-record correction data migration checks."""

from datetime import date
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.apps import apps
from django.db import connection
from django.test import TestCase

from attendance.models import WorkSession
from auditlog.models import AuditLog
from corrections.models import CorrectionRequest
from corrections.services import submit_correction


class LegacyNoRecordMigrationTests(TestCase):
    def test_only_evidenced_empty_placeholder_is_removed(self):
        employee = get_user_model().objects.create_user(
            employee_number="0081", password="TestPassword_2026!",
        )
        day = date(2024, 1, 2)
        placeholder = WorkSession.objects.create(
            employee=employee, work_date=day,
            status=WorkSession.Status.NO_RECORD,
        )
        untouched = WorkSession.objects.create(
            employee=employee, work_date=date(2024, 1, 3),
            status=WorkSession.Status.NO_RECORD,
        )
        correction = CorrectionRequest.objects.create(
            work_session=placeholder, requested_by=employee,
            original_version=1, proposal={}, reason="旧申請",
        )
        AuditLog.objects.create(
            actor=employee, target_employee=employee,
            action=AuditLog.Action.CORRECTION_SUBMIT,
            target_model="CorrectionRequest", target_id=str(correction.pk),
            before_data={"clock_in_at": None, "clock_out_at": None, "breaks": []},
            after_data={}, reason="旧申請", details={"original_version": 1},
        )
        migration = import_module("corrections.migrations.0004_convert_legacy_empty_sessions")
        migration.convert_legacy_empty_sessions(apps, SimpleNamespace(connection=connection))
        correction.refresh_from_db()
        self.assertIsNone(correction.work_session_id)
        self.assertIsNone(correction.original_version)
        self.assertEqual(correction.employee_id, employee.pk)
        self.assertEqual(correction.work_date, day)
        self.assertFalse(WorkSession.objects.filter(pk=placeholder.pk).exists())
        self.assertTrue(WorkSession.objects.filter(pk=untouched.pk).exists())


class CorrectionRollbackTests(TestCase):
    def test_notification_failure_rolls_back_no_record_application(self):
        employee = get_user_model().objects.create_user(
            employee_number="0082", password="TestPassword_2026!",
            hire_date=date(2024, 1, 1),
        )
        day = date(2024, 1, 2)
        proposal = {
            "clock_in_at": "2024-01-02T09:00:00+09:00",
            "clock_out_at": "2024-01-02T18:00:00+09:00",
            "breaks": [],
        }
        with patch("corrections.services.notify_correction_submitted", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                submit_correction(
                    employee_id=employee.pk, work_day=day, expected_version=0,
                    proposal=proposal, reason="打刻漏れ",
                )
        self.assertFalse(CorrectionRequest.objects.exists())
        self.assertFalse(WorkSession.objects.filter(employee=employee, work_date=day).exists())
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.CORRECTION_SUBMIT).exists())
