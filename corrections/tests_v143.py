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
