"""Occurrence identity survives notification cleanup and detects recurrence."""

from datetime import date, datetime
from importlib import import_module
from zoneinfo import ZoneInfo

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from attendance.incomplete import sync_incomplete_occurrences
from attendance.models import IncompleteOccurrence, WorkSession
from notifications.models import Notification


class IncompleteOccurrenceTests(TestCase):
    def test_migration_carries_forward_legacy_recipient_ids(self):
        Employee = get_user_model()
        employee = Employee.objects.create_user(
            employee_number="0011", password="TestPassword_2026!",
            hire_date=date(2024, 1, 1),
        )
        manager = Employee.objects.create_user(
            employee_number="9011", password="TestPassword_2026!",
            is_business_admin=True,
        )
        session = WorkSession.objects.create(
            employee=employee, work_date=date(2024, 1, 2),
            clock_in_at=datetime(2024, 1, 2, 9, tzinfo=ZoneInfo("Asia/Tokyo")),
            status=WorkSession.Status.WORKING, incomplete_notified_version=1,
        )
        for recipient in (employee, manager):
            Notification.objects.create(
                recipient=recipient, kind=Notification.Kind.INCOMPLETE,
                title="未完了", body="未完了の勤怠", event_key=f"incomplete:{session.pk}:v1:{recipient.pk}",
            )
        migration = import_module("attendance.migrations.0004_incomplete_occurrences")
        migration.carry_forward(apps, None)
        occurrence = IncompleteOccurrence.objects.get(work_session=session)
        self.assertEqual(set(occurrence.recipient_ids), {employee.pk, manager.pk})
        self.assertEqual(set(occurrence.notified_recipient_ids), {employee.pk, manager.pk})

    def test_cleanup_does_not_recreate_same_occurrence(self):
        Employee = get_user_model()
        employee = Employee.objects.create_user(
            employee_number="0007", password="TestPassword_2026!",
            hire_date=date(2024, 1, 1),
        )
        session = WorkSession.objects.create(
            employee=employee, work_date=date(2024, 1, 2),
            clock_in_at=datetime(2024, 1, 2, 9, tzinfo=ZoneInfo("Asia/Tokyo")),
            status=WorkSession.Status.WORKING,
        )
        sync_incomplete_occurrences(session)
        first = IncompleteOccurrence.objects.get(work_session=session)
        call_command("notify_incomplete")
        self.assertEqual(Notification.objects.filter(recipient=employee).count(), 1)
        Notification.objects.all().delete()
        call_command("notify_incomplete")
        self.assertEqual(Notification.objects.count(), 0)

        session.clock_out_at = datetime(2024, 1, 2, 18, tzinfo=ZoneInfo("Asia/Tokyo"))
        session.status = WorkSession.Status.COMPLETED
        session.save(update_fields=["clock_out_at", "status"])
        sync_incomplete_occurrences(session)
        first.refresh_from_db()
        self.assertIsNotNone(first.ended_at)

        session.clock_out_at = None
        session.status = WorkSession.Status.WORKING
        session.save(update_fields=["clock_out_at", "status"])
        sync_incomplete_occurrences(session)
        second = IncompleteOccurrence.objects.get(work_session=session, ended_at__isnull=True)
        self.assertNotEqual(first.occurrence_id, second.occurrence_id)
        call_command("notify_incomplete")
        self.assertEqual(Notification.objects.filter(recipient=employee).count(), 1)
