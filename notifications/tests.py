

# 通知
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from attendance.models import WorkSession
from corrections.models import CorrectionRequest

from .models import Notification
from .services import (
    create_notification,
    notify_correction_submitted,
    notify_correction_reviewed,
)


class NotificationTests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.employee = Employee.objects.create_user(
            employee_number="97001",
            password="NotifyEmployee_2026!",
            first_name="一般",
            last_name="社員",
        )

        self.manager = Employee.objects.create_user(
            employee_number="97002",
            password="NotifyManager_2026!",
            first_name="管理",
            last_name="担当",
            is_business_admin=True,
        )

        jst = ZoneInfo("Asia/Tokyo")

        self.work = WorkSession.objects.create(
            employee=self.employee,
            work_date=date(2026, 10, 15),
            clock_in_at=datetime(
                2026,
                10,
                15,
                9,
                tzinfo=jst,
            ),
            clock_out_at=datetime(
                2026,
                10,
                15,
                18,
                tzinfo=jst,
            ),
            status=WorkSession.Status.COMPLETED,
        )

        self.correction = CorrectionRequest.objects.create(
            work_session=self.work,
            requested_by=self.employee,
            original_version=self.work.version,
            proposal={},
            reason="時刻を修正するため",
            status=CorrectionRequest.Status.PENDING,
        )

    def make_user_notification(self, target_path=None):
        return create_notification(
            recipient=self.employee,
            kind=Notification.Kind.GENERAL,
            title="テスト通知",
            body="確認用のお知らせです。",
            target_path=(
                target_path if target_path is not None else reverse("attendance:home")
            ),
        )

    def test_stopped_employee_result_opens_application_detail_for_manager(self):
        self.employee.is_active = False
        self.employee.save(update_fields=["is_active"])
        self.correction.status = CorrectionRequest.Status.RETURNED
        notify_correction_reviewed(self.correction)
        notice = Notification.objects.get(
            recipient=self.manager,
            kind=Notification.Kind.CORRECTION_RETURNED,
        )
        self.assertEqual(
            notice.target_path,
            reverse("management:correction_detail", args=[self.correction.pk]),
        )

    def test_01_anonymous_redirect(self):
        response = self.client.get(reverse("notifications:list"))

        self.assertEqual(response.status_code, 302)

    def test_02_submission_notifies_manager_once(self):
        notify_correction_submitted(self.correction)
        notify_correction_submitted(self.correction)

        self.assertEqual(
            Notification.objects.filter(
                recipient=self.manager,
                kind=Notification.Kind.CORRECTION_SUBMITTED,
            ).count(),
            1,
        )

    def test_03_approval_notifies_employee(self):
        self.correction.status = CorrectionRequest.Status.APPROVED

        notify_correction_reviewed(self.correction)

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.employee,
                kind=Notification.Kind.CORRECTION_APPROVED,
            ).exists()
        )

    def test_04_other_user_cannot_open_notification(self):
        notify_correction_submitted(self.correction)

        notification = Notification.objects.get(
            recipient=self.manager,
        )

        self.client.force_login(self.employee)

        response = self.client.post(
            reverse(
                "notifications:open",
                args=[notification.pk],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_05_open_marks_as_read_after_destination_loads(self):
        notification = self.make_user_notification()

        self.client.force_login(self.employee)

        response = self.client.post(
            reverse(
                "notifications:open",
                args=[notification.pk],
            )
        )

        self.assertEqual(response.status_code, 302)

        notification.refresh_from_db()
        self.assertIsNone(notification.read_at)
        self.client.get(response.url)
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

    def test_06_external_redirect_rejected(self):
        notification = self.make_user_notification(target_path="//example.invalid/")

        self.client.force_login(self.employee)

        response = self.client.post(
            reverse(
                "notifications:open",
                args=[notification.pk],
            )
        )

        self.assertTrue(response.url.startswith(reverse("notifications:list")))
        self.client.get(response.url)
        notification.refresh_from_db()
        self.assertIsNone(notification.read_at)

    def test_07_read_all_only_affects_owner(self):
        own = self.make_user_notification()

        other = create_notification(
            recipient=self.manager,
            kind=Notification.Kind.GENERAL,
            title="管理者向け",
            body="管理者向けの通知です。",
        )

        self.client.force_login(self.employee)

        self.client.post(reverse("notifications:read_all"))

        own.refresh_from_db()
        other.refresh_from_db()

        self.assertIsNotNone(own.read_at)
        self.assertIsNone(other.read_at)

    def test_08_read_all_keeps_later_notification_unread(self):
        later = self.make_user_notification()
        later.created_at = timezone.now() + timedelta(minutes=1)
        later.save(update_fields=["created_at"])
        self.client.force_login(self.employee)
        self.client.post(reverse("notifications:read_all"))
        later.refresh_from_db()
        self.assertIsNone(later.read_at)

    def test_09_panel_limits_to_20_and_badge_caps_at_99(self):
        Notification.objects.bulk_create([
            Notification(recipient=self.employee, kind=Notification.Kind.GENERAL,
                         title=f"通知{i}", body="確認") for i in range(100)
        ])
        self.client.force_login(self.employee)
        page = self.client.get(reverse("attendance:home"))
        self.assertContains(page, "99+")
        panel = self.client.get(reverse("notifications:panel")).json()
        self.assertEqual(panel["unread_count"], 100)
        self.assertEqual(len(panel["items"]), 20)


# 未完了通知
"""未完了勤務通知のテスト。"""

from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from attendance.models import (
    MonthlyClosing,
    WorkSession,
)
from corrections.models import CorrectionRequest
from notifications.models import Notification


class IncompleteNotificationTests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.employee = Employee.objects.create_user(
            employee_number="99701",
            password="NoticeTest_2026!",
        )

        self.manager = Employee.objects.create_user(
            employee_number="99702",
            password="NoticeManager_2026!",
            is_business_admin=True,
        )

        self.work_day = timezone.localdate() - timedelta(days=3)

    def create_working_session(self):
        return WorkSession.objects.create(
            employee=self.employee,
            work_date=self.work_day,
            clock_in_at=(timezone.now() - timedelta(days=3)),
            status=WorkSession.Status.WORKING,
        )

    def execute(self, **options):
        output = StringIO()

        call_command(
            "notify_incomplete",
            stdout=output,
            **options,
        )

        return output.getvalue()

    def test_01_incomplete_creates_notification(self):
        self.create_working_session()

        self.execute(days=2)

        self.assertEqual(
            Notification.objects.filter(
                recipient=self.employee,
            ).count(),
            1,
        )

    def test_02_repeat_does_not_duplicate(self):
        self.create_working_session()

        self.execute(days=2)
        self.execute(days=2)

        self.assertEqual(
            Notification.objects.count(),
            2,
        )

    def test_02b_manager_is_notified_and_role_loss_hides_notice(self):
        self.create_working_session()
        self.execute()
        notice = Notification.objects.get(recipient=self.manager)
        self.assertTrue(notice.is_management)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("notifications:panel")).json()["unread_count"], 1)
        Employee = get_user_model()
        for number in ("9901", "9902"):
            Employee.objects.create_user(
                employee_number=number, password="TestPassword_2026!",
                is_business_admin=True,
            )
        self.manager.is_business_admin = False
        self.manager.save(update_fields=["is_business_admin"])
        self.assertEqual(self.client.get(reverse("notifications:panel")).json()["unread_count"], 0)
        self.assertEqual(self.client.post(reverse("notifications:open", args=[notice.pk])).status_code, 404)

    def test_02c_expired_notification_does_not_repeat_until_resolved(self):
        session = self.create_working_session()
        self.execute()
        Notification.objects.all().delete()
        self.execute()
        self.assertFalse(Notification.objects.exists())
        session.version += 1
        session.save(update_fields=["version"])
        self.execute()
        self.assertFalse(Notification.objects.exists())
        session.status = WorkSession.Status.COMPLETED
        session.clock_out_at = timezone.now()
        session.incomplete_notified_version = None
        session.save(update_fields=["status", "clock_out_at", "incomplete_notified_version"])
        from attendance.incomplete import sync_incomplete_occurrences
        sync_incomplete_occurrences(session)
        session.status = WorkSession.Status.WORKING
        session.clock_out_at = None
        session.version += 1
        session.save(update_fields=["status", "clock_out_at", "version"])
        sync_incomplete_occurrences(session)
        self.execute()
        self.assertEqual(Notification.objects.count(), 2)

    def test_02d_cleanup_only_removes_old_notifications(self):
        old = Notification.objects.create(
            recipient=self.employee, kind=Notification.Kind.GENERAL,
            title="古い通知", body="削除対象",
            created_at=timezone.now() - timedelta(days=91),
        )
        recent = Notification.objects.create(
            recipient=self.employee, kind=Notification.Kind.GENERAL,
            title="新しい通知", body="残す通知",
        )
        call_command("cleanup_notifications", stdout=StringIO())
        self.assertFalse(Notification.objects.filter(pk=old.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=recent.pk).exists())

    def test_03_dry_run_does_not_save(self):
        session = self.create_working_session()

        self.execute(
            days=2,
            dry_run=True,
        )

        self.assertFalse(Notification.objects.exists())
        from attendance.models import IncompleteOccurrence
        self.assertFalse(IncompleteOccurrence.objects.filter(work_session=session).exists())

    def test_04_pending_request_does_not_hide_open_occurrence(self):
        session = self.create_working_session()

        CorrectionRequest.objects.create(
            work_session=session,
            requested_by=self.employee,
            original_version=session.version,
            proposal={},
            reason="勤務時刻を確認するため",
            status=CorrectionRequest.Status.PENDING,
        )

        self.execute(days=2)

        self.assertEqual(Notification.objects.count(), 2)

    def test_05_inactive_subject_notifies_manager_only(self):
        self.create_working_session()

        self.employee.is_active = False
        self.employee.save(update_fields=["is_active"])

        self.execute(days=2)

        self.assertEqual(Notification.objects.filter(recipient=self.manager).count(), 1)
        self.assertFalse(Notification.objects.filter(recipient=self.employee).exists())

    def test_06_legacy_inconsistent_finalized_month_is_reported(self):
        self.create_working_session()

        MonthlyClosing.objects.create(
            employee=self.employee,
            target_month=(self.work_day.replace(day=1)),
            status=MonthlyClosing.Status.FINALIZED,
            finalized_by=self.manager,
            finalized_at=timezone.now(),
        )

        self.execute(days=2)

        self.assertEqual(Notification.objects.count(), 2)


# v1.4.3 通知の回帰試験

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
