import uuid

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from auditlog.models import AuditLog
from corrections.models import CorrectionRequest

from attendance.models import (
    BreakInterval,
    ClockEvent,
    MonthlyClosing,
    WorkSession,
)
from attendance.services import (
    ClockActionError,
    record_clock_action,
)


class ClockActionTests(TestCase):
    """Phase 5の打刻機能テスト。"""

    def setUp(self):
        Employee = get_user_model()

        self.employee = Employee.objects.create_user(
            employee_number="80001",
            password="ClockTest_2026!Password",
            last_name="テスト",
            first_name="社員",
        )

        self.manager = Employee.objects.create_user(
            employee_number="80002",
            password="ManagerTest_2026!Password",
            is_business_admin=True,
        )

        self.jst = ZoneInfo("Asia/Tokyo")

    def dt(self, year, month, day, hour, minute=0):
        """日本時間の日時を作成する。"""

        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=self.jst,
        )

    def record_at(
        self,
        kind,
        when,
        operation_id=None,
        employee_id=None,
    ):
        """指定日時で打刻サービスを実行する。"""

        if operation_id is None:
            operation_id = uuid.uuid4()

        if employee_id is None:
            employee_id = self.employee.pk

        with patch(
            "attendance.services.timezone.now",
            return_value=when,
        ):
            return record_clock_action(
                employee_id=employee_id,
                kind=kind,
                operation_id=operation_id,
            )

    def test_normal_work_flow(self):
        """基本的な出退勤・休憩を記録できる。"""

        self.record_at(
            "clock_in",
            self.dt(2026, 10, 15, 9),
        )

        self.record_at(
            "break_start",
            self.dt(2026, 10, 15, 12),
        )

        self.record_at(
            "break_end",
            self.dt(2026, 10, 15, 13),
        )

        self.record_at(
            "clock_out",
            self.dt(2026, 10, 15, 18),
        )

        session = WorkSession.objects.get(
            employee=self.employee,
            work_date=date(2026, 10, 15),
        )

        self.assertEqual(
            session.status,
            WorkSession.Status.COMPLETED,
        )

        self.assertEqual(
            ClockEvent.objects.count(),
            4,
        )

        self.assertEqual(
            AuditLog.objects.filter(action=AuditLog.Action.CLOCK).count(),
            4,
        )

        self.assertEqual(
            session.version,
            4,
        )

    def test_same_operation_id_is_idempotent(self):
        """同じ操作IDの再送で重複登録しない。"""

        operation_id = uuid.uuid4()

        self.record_at(
            "clock_in",
            self.dt(2026, 10, 15, 9),
            operation_id,
        )

        result = self.record_at(
            "clock_in",
            self.dt(2026, 10, 15, 9),
            operation_id,
        )

        self.assertTrue(result.already_recorded)

        self.assertEqual(
            ClockEvent.objects.count(),
            1,
        )

    def test_double_clock_in_rejected(self):
        """勤務中の追加出勤は拒否される。"""

        self.record_at(
            "clock_in",
            self.dt(2026, 10, 15, 9),
        )

        with self.assertRaises(ClockActionError):
            self.record_at(
                "clock_in",
                self.dt(2026, 10, 15, 10),
            )

        self.assertEqual(
            ClockEvent.objects.count(),
            1,
        )

    def test_break_before_clock_in_rejected(self):
        """未出勤では休憩開始できない。"""

        with self.assertRaises(ClockActionError):
            self.record_at(
                "break_start",
                self.dt(2026, 10, 15, 12),
            )

    def test_clock_out_during_break_rejected(self):
        """休憩中に退勤できない。"""

        self.record_at(
            "clock_in",
            self.dt(2026, 10, 15, 9),
        )

        self.record_at(
            "break_start",
            self.dt(2026, 10, 15, 12),
        )

        with self.assertRaises(ClockActionError):
            self.record_at(
                "clock_out",
                self.dt(2026, 10, 15, 12, 30),
            )

        self.assertEqual(
            ClockEvent.objects.count(),
            2,
        )

    def test_multiple_breaks(self):
        """1勤務内に複数休憩を記録できる。"""

        self.record_at(
            "clock_in",
            self.dt(2026, 10, 15, 9),
        )

        self.record_at(
            "break_start",
            self.dt(2026, 10, 15, 12),
        )

        self.record_at(
            "break_end",
            self.dt(2026, 10, 15, 13),
        )

        self.record_at(
            "break_start",
            self.dt(2026, 10, 15, 15),
        )

        self.record_at(
            "break_end",
            self.dt(2026, 10, 15, 15, 15),
        )

        self.record_at(
            "clock_out",
            self.dt(2026, 10, 15, 18),
        )

        session = WorkSession.objects.get(
            employee=self.employee,
        )

        breaks = BreakInterval.objects.filter(
            work_session=session,
        )

        self.assertEqual(
            breaks.count(),
            2,
        )

        total_break_seconds = sum(
            int((item.ended_at - item.started_at).total_seconds()) for item in breaks
        )

        self.assertEqual(
            total_break_seconds,
            75 * 60,
        )

    def test_overnight_work(self):
        """翌日退勤を出勤日の勤務に記録する。"""

        self.record_at(
            "clock_in",
            self.dt(2026, 10, 31, 22),
        )

        self.record_at(
            "break_start",
            self.dt(2026, 11, 1, 1),
        )

        self.record_at(
            "break_end",
            self.dt(2026, 11, 1, 2),
        )

        self.record_at(
            "clock_out",
            self.dt(2026, 11, 1, 7),
        )

        session = WorkSession.objects.get(
            employee=self.employee,
        )

        self.assertEqual(
            session.work_date,
            date(2026, 10, 31),
        )

        self.assertEqual(
            session.status,
            WorkSession.Status.COMPLETED,
        )

        self.assertEqual(
            timezone_to_jst_date(session.clock_out_at),
            date(2026, 11, 1),
        )

    def test_pending_correction_blocks_clock(self):
        """申請審査中は追加打刻できない。"""

        result = self.record_at(
            "clock_in",
            self.dt(2026, 10, 15, 9),
        )

        CorrectionRequest.objects.create(
            work_session=result.session,
            requested_by=self.employee,
            original_version=result.session.version,
            proposal={},
            reason="テスト申請",
        )

        with self.assertRaises(ClockActionError):
            self.record_at(
                "clock_out",
                self.dt(2026, 10, 15, 18),
            )

    def test_finalized_month_blocks_clock_in(self):
        """確定済みの月に新規打刻できない。"""

        MonthlyClosing.objects.create(
            employee=self.employee,
            target_month=date(2026, 10, 1),
            status=MonthlyClosing.Status.FINALIZED,
            finalized_by=self.manager,
            finalized_at=self.dt(2026, 11, 1, 10),
        )

        with self.assertRaises(ClockActionError):
            self.record_at(
                "clock_in",
                self.dt(2026, 10, 15, 9),
            )

    def test_clock_endpoint_requires_post(self):
        """打刻URLにGETで登録できない。"""

        self.client.force_login(self.employee)

        response = self.client.get(reverse("attendance:clock_action"))

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_clock_endpoint_post(self):
        """ブラウザからのPOSTで打刻を登録できる。"""

        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("attendance:clock_action"),
            {
                "action": "clock_in",
                "operation_id": str(uuid.uuid4()),
            },
        )

        self.assertRedirects(
            response,
            reverse("attendance:home"),
        )

        self.assertEqual(
            ClockEvent.objects.count(),
            1,
        )

    def test_other_employee_cannot_reuse_operation_id(self):
        """他人の操作IDを再利用できない。"""

        operation_id = uuid.uuid4()

        self.record_at(
            "clock_in",
            self.dt(2026, 10, 15, 9),
            operation_id,
        )

        with self.assertRaises(ClockActionError):
            self.record_at(
                "clock_in",
                self.dt(2026, 10, 15, 9),
                operation_id,
                employee_id=self.manager.pk,
            )

        self.assertEqual(
            ClockEvent.objects.count(),
            1,
        )


def timezone_to_jst_date(value):
    """日時を日本時間の日付に変換する。"""

    from django.utils import timezone

    return timezone.localtime(
        value,
        ZoneInfo("Asia/Tokyo"),
    ).date()
