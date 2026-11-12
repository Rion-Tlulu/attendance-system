# 勤務記録・基本規則

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
            2026,
            10,
            15,
            9,
            0,
            tzinfo=jst,
        )

        self.clock_out = datetime(
            2026,
            10,
            15,
            18,
            0,
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

        self.assertTrue(self.employee.check_password("TestOnly_2026!Password"))

    def test_work_duration(self):
        jst = ZoneInfo("Asia/Tokyo")

        break_start = datetime(
            2026,
            10,
            15,
            12,
            0,
            tzinfo=jst,
        )

        break_end = datetime(
            2026,
            10,
            15,
            13,
            0,
            tzinfo=jst,
        )

        rest = BreakInterval.objects.create(
            work_session=self.session,
            started_at=break_start,
            ended_at=break_end,
        )

        work_seconds = (
            self.session.clock_out_at - self.session.clock_in_at
        ).total_seconds()

        break_seconds = (rest.ended_at - rest.started_at).total_seconds()

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


# 打刻
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

    def test_stale_clock_in_day_is_rejected(self):
        with patch("attendance.services.timezone.now", return_value=self.dt(2026, 10, 16, 9)):
            with self.assertRaisesRegex(ClockActionError, "古い出勤画面"):
                record_clock_action(
                    employee_id=self.employee.pk,
                    kind="clock_in",
                    operation_id=uuid.uuid4(),
                    expected_work_date=date(2026, 10, 15),
                )
        self.assertFalse(ClockEvent.objects.exists())

    def test_stale_session_version_and_reused_id_with_changed_content_are_rejected(self):
        day = date(2026, 10, 15)
        operation_id = uuid.uuid4()
        with patch("attendance.services.timezone.now", return_value=self.dt(2026, 10, 15, 9)):
            first = record_clock_action(
                employee_id=self.employee.pk,
                kind="clock_in",
                operation_id=operation_id,
                expected_work_date=day,
            )
            replay = record_clock_action(
                employee_id=self.employee.pk,
                kind="clock_in",
                operation_id=operation_id,
                expected_work_date=day,
            )
            self.assertTrue(replay.already_recorded)
            with self.assertRaisesRegex(ClockActionError, "操作ID"):
                record_clock_action(
                    employee_id=self.employee.pk,
                    kind="clock_in",
                    operation_id=operation_id,
                    expected_work_date=day,
                    expected_session_id=first.session.pk,
                    expected_version=first.session.version,
                )
            with self.assertRaisesRegex(ClockActionError, "更新されました"):
                record_clock_action(
                    employee_id=self.employee.pk,
                    kind="break_start",
                    operation_id=uuid.uuid4(),
                    expected_work_date=day,
                    expected_session_id=first.session.pk,
                    expected_version=first.session.version - 1,
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

    def test_clock_in_reuses_no_record_after_withdrawal(self):
        """記録なしの日の申請を取り下げた後は出勤できる。"""
        placeholder = WorkSession.objects.create(
            employee=self.employee,
            work_date=date(2026, 10, 15),
            status=WorkSession.Status.NO_RECORD,
        )
        CorrectionRequest.objects.create(
            work_session=placeholder,
            requested_by=self.employee,
            original_version=placeholder.version,
            proposal={},
            reason="打刻前の申請を取り下げた",
            status=CorrectionRequest.Status.WITHDRAWN,
        )

        result = self.record_at(
            "clock_in",
            self.dt(2026, 10, 15, 9),
        )

        self.assertEqual(result.session.pk, placeholder.pk)
        self.assertEqual(result.session.status, WorkSession.Status.WORKING)
        self.assertEqual(ClockEvent.objects.count(), 1)

    def test_clock_in_blocks_pending_no_record_request(self):
        """記録なしの日でも審査中は出勤できない。"""
        placeholder = WorkSession.objects.create(
            employee=self.employee,
            work_date=date(2026, 10, 15),
            status=WorkSession.Status.NO_RECORD,
        )
        CorrectionRequest.objects.create(
            work_session=placeholder,
            requested_by=self.employee,
            original_version=placeholder.version,
            proposal={},
            reason="審査中の申請",
        )

        with self.assertRaises(ClockActionError):
            self.record_at("clock_in", self.dt(2026, 10, 15, 9))

        self.assertEqual(ClockEvent.objects.count(), 0)

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
                "work_date": timezone.localdate().isoformat(),
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


# 月次集計
import uuid

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from attendance.models import (
    BreakInterval,
    ClockEvent,
    MonthlyClosing,
    WorkSession,
)
from attendance.reporting import (
    build_comparison_rows,
    build_daily_row,
    build_monthly_report,
    calculate_duration,
    format_duration,
)
from corrections.models import CorrectionRequest


class Phase6Tests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.employee = Employee.objects.create_user(
            employee_number="81001",
            password="MonthlyTest_2026!",
            first_name="花子",
            last_name="山田",
        )

        self.other = Employee.objects.create_user(
            employee_number="81002",
            password="OtherMonthly_2026!",
            first_name="太郎",
            last_name="佐藤",
        )

        self.manager = Employee.objects.create_user(
            employee_number="81003",
            password="ManagerMonthly_2026!",
            is_business_admin=True,
        )

        self.jst = ZoneInfo("Asia/Tokyo")

    def dt(self, day, hour, minute=0, second=0):
        return datetime(
            day.year,
            day.month,
            day.day,
            hour,
            minute,
            second,
            tzinfo=self.jst,
        )

    def create_work(self, day, employee=None):
        return WorkSession.objects.create(
            employee=employee or self.employee,
            work_date=day,
            clock_in_at=self.dt(day, 9),
            clock_out_at=self.dt(day, 18),
            status=WorkSession.Status.COMPLETED,
        )

    def create_break(self, session, start, end):
        return BreakInterval.objects.create(
            work_session=session,
            started_at=start,
            ended_at=end,
        )

    def test_duration_format(self):
        self.assertEqual(
            format_duration(8 * 3600 + 125),
            "8時間02分",
        )

    def test_normal_work(self):
        day = date(2026, 9, 15)
        work = self.create_work(day)

        rest = self.create_break(
            work,
            self.dt(day, 12),
            self.dt(day, 13),
        )

        result = calculate_duration(work, [rest])

        self.assertTrue(result.complete)
        self.assertEqual(result.work_seconds, 28800)
        self.assertEqual(result.break_seconds, 3600)

    def test_multiple_breaks(self):
        day = date(2026, 9, 15)
        work = self.create_work(day)

        first = self.create_break(
            work,
            self.dt(day, 12),
            self.dt(day, 12, 45),
        )

        second = self.create_break(
            work,
            self.dt(day, 15),
            self.dt(day, 15, 15),
        )

        result = calculate_duration(work, [first, second])

        self.assertTrue(result.complete)
        self.assertEqual(result.break_seconds, 3600)
        self.assertEqual(result.work_seconds, 28800)

    def test_monthly_seconds(self):
        for number in (10, 11, 12):
            day = date(2026, 9, number)

            WorkSession.objects.create(
                employee=self.employee,
                work_date=day,
                clock_in_at=self.dt(day, 9),
                clock_out_at=self.dt(day, 17, 0, 40),
                status=WorkSession.Status.COMPLETED,
            )

        report = build_monthly_report(
            self.employee,
            date(2026, 9, 1),
        )

        self.assertEqual(
            report.work_display,
            "24時間02分",
        )

    def test_incomplete_work(self):
        day = date(2026, 9, 15)

        WorkSession.objects.create(
            employee=self.employee,
            work_date=day,
            clock_in_at=self.dt(day, 9),
            status=WorkSession.Status.WORKING,
        )

        report = build_monthly_report(
            self.employee,
            date(2026, 9, 1),
        )

        self.assertEqual(report.incomplete_count, 1)
        self.assertEqual(report.total_work_seconds, 0)

    def test_no_record(self):
        row = build_daily_row(
            date(2026, 9, 15),
            None,
        )

        self.assertEqual(row.record_key, "no_record")
        self.assertIsNone(row.work_seconds)
        self.assertEqual(row.work_display, "—")

    def test_overlapping_breaks(self):
        day = date(2026, 9, 15)
        work = self.create_work(day)

        first = self.create_break(
            work,
            self.dt(day, 12),
            self.dt(day, 13),
        )

        second = self.create_break(
            work,
            self.dt(day, 12, 30),
            self.dt(day, 13, 30),
        )

        result = calculate_duration(work, [first, second])

        self.assertFalse(result.complete)

    def test_overnight_work(self):
        start_day = date(2026, 9, 30)
        next_day = date(2026, 10, 1)

        work = WorkSession.objects.create(
            employee=self.employee,
            work_date=start_day,
            clock_in_at=self.dt(start_day, 22),
            clock_out_at=self.dt(next_day, 7),
            status=WorkSession.Status.COMPLETED,
        )

        self.create_break(
            work,
            self.dt(next_day, 1),
            self.dt(next_day, 2),
        )

        september = build_monthly_report(
            self.employee,
            date(2026, 9, 1),
        )

        october = build_monthly_report(
            self.employee,
            date(2026, 10, 1),
        )

        self.assertEqual(
            september.total_work_seconds,
            28800,
        )

        self.assertEqual(
            october.total_work_seconds,
            0,
        )

    def test_pending_correction(self):
        day = date(2026, 9, 15)
        work = self.create_work(day)

        CorrectionRequest.objects.create(
            work_session=work,
            requested_by=self.employee,
            original_version=work.version,
            proposal={},
            reason="退勤時刻を修正したいため",
        )

        report = build_monthly_report(
            self.employee,
            date(2026, 9, 1),
        )

        self.assertEqual(report.pending_count, 1)

        row = next(item for item in report.rows if item.day == day)

        self.assertEqual(row.record_label, "記録済み")
        self.assertEqual(row.correction_label, "審査中")
        self.assertEqual(row.closing_label, "未確定")

    def test_finalized_month(self):
        MonthlyClosing.objects.create(
            employee=self.employee,
            target_month=date(2026, 9, 1),
            status=MonthlyClosing.Status.FINALIZED,
            finalized_by=self.manager,
            finalized_at=self.dt(date(2026, 10, 1), 10),
        )

        report = build_monthly_report(
            self.employee,
            date(2026, 9, 1),
        )

        self.assertTrue(report.is_finalized)
        self.assertEqual(report.closing_label, "確定済み")

    def test_seven_day_pagination(self):
        self.client.force_login(self.employee)

        response = self.client.get(
            reverse("attendance:monthly"),
            {"month": "2026-09"},
        )

        self.assertEqual(response.status_code, 200)

        page = response.context["page_obj"]

        self.assertEqual(len(page.object_list), 7)
        self.assertEqual(page.paginator.num_pages, 5)
        self.assertEqual(
            page.object_list[0].day,
            date(2026, 9, 30),
        )

    def test_second_page(self):
        self.client.force_login(self.employee)

        response = self.client.get(
            reverse("attendance:monthly"),
            {
                "month": "2026-09",
                "page": "2",
            },
        )

        page = response.context["page_obj"]

        self.assertEqual(page.number, 2)
        self.assertEqual(
            page.object_list[0].day,
            date(2026, 9, 23),
        )

    def test_original_vs_effective(self):
        day = date(2026, 9, 15)
        work = self.create_work(day)

        ClockEvent.objects.create(
            work_session=work,
            kind=ClockEvent.Kind.CLOCK_IN,
            recorded_at=self.dt(day, 9),
            operation_id=uuid.uuid4(),
        )

        work.clock_in_at = self.dt(day, 9, 15)
        work.save(update_fields=["clock_in_at"])

        events = list(ClockEvent.objects.filter(work_session=work))

        rows = build_comparison_rows(
            work,
            [],
            events,
        )

        self.assertIn("09:00", rows[0].original)
        self.assertIn("09:15", rows[0].effective)

    def test_other_employee_is_hidden(self):
        day = date(2026, 9, 15)

        self.create_work(
            day,
            employee=self.other,
        )

        self.client.force_login(self.employee)

        response = self.client.get(
            reverse(
                "attendance:daily",
                args=[2026, 9, 15],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["session"])
        self.assertEqual(
            response.context["summary"].record_key,
            "no_record",
        )

    def test_invalid_month(self):
        self.client.force_login(self.employee)

        response = self.client.get(
            reverse("attendance:monthly"),
            {"month": "2026-13"},
        )

        self.assertEqual(response.status_code, 400)

    def test_invalid_date(self):
        self.client.force_login(self.employee)

        response = self.client.get(
            reverse(
                "attendance:daily",
                args=[2026, 2, 30],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_anonymous_access(self):
        response = self.client.get(reverse("attendance:monthly"))

        self.assertEqual(response.status_code, 302)


# E01 打刻ホーム
"""E01 打刻ホームの表示テスト。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from attendance.models import WorkSession
from corrections.models import CorrectionRequest


class E01ClockHomeTests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.employee = Employee.objects.create_user(
            employee_number="99001",
            password="ClockUiTest_2026!",
            first_name="テスト",
            last_name="社員",
        )

        self.url = reverse("attendance:home")
        self.today = timezone.localdate()

        self.client.force_login(self.employee)

    def create_session(self, status):
        return WorkSession.objects.create(
            employee=self.employee,
            work_date=self.today,
            clock_in_at=timezone.now(),
            status=status,
        )

    def test_01_home_opens(self):
        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            "打刻操作",
        )

        self.assertContains(
            response,
            "今日の記録",
        )

    def test_02_no_record_allows_clock_in(self):
        response = self.client.get(self.url)

        self.assertContains(response, 'name="action"\n') if False else None

        self.assertContains(
            response,
            'value="clock_in"',
        )

        self.assertContains(
            response,
            'name="operation_id"',
        )

        self.assertNotContains(
            response,
            'value="clock_out"',
        )

    def test_03_working_allows_two_actions(self):
        self.create_session(WorkSession.Status.WORKING)

        response = self.client.get(self.url)

        self.assertContains(
            response,
            'value="clock_out"',
        )

        self.assertContains(
            response,
            'value="break_start"',
        )

        self.assertNotContains(
            response,
            'value="break_end"',
        )

    def test_04_on_break_allows_break_end(self):
        self.create_session(WorkSession.Status.ON_BREAK)

        response = self.client.get(self.url)

        self.assertContains(
            response,
            'value="break_end"',
        )

        self.assertNotContains(
            response,
            'value="clock_out"',
        )

    def test_05_pending_request_disables_clock(self):
        session = self.create_session(WorkSession.Status.WORKING)

        CorrectionRequest.objects.create(
            work_session=session,
            requested_by=self.employee,
            original_version=session.version,
            proposal={},
            reason="時刻を確認するため",
            status=CorrectionRequest.Status.PENDING,
        )

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            "修正申請が審査中",
        )

        self.assertNotContains(
            response,
            'value="clock_out"',
        )

        self.assertNotContains(
            response,
            'value="break_start"',
        )

    def test_06_mobile_layout_exists(self):
        response = self.client.get(self.url)

        self.assertContains(
            response,
            "e01-main-grid",
        )

        self.assertContains(
            response,
            "e01-clock-panel",
        )

        self.assertContains(
            response,
            "e01-history-panel",
        )


# E02 月次勤怠
"""E02 自分の勤怠（月次一覧）の表示テスト。"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase

from attendance.models import WorkSession


class E02MonthlyUiTests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.employee = Employee.objects.create_user(
            employee_number="99101",
            password="MonthlyUiTest_2026!",
            first_name="テスト",
            last_name="社員",
        )

        self.url = "/employee/monthly/"
        self.client.force_login(self.employee)

    def test_01_monthly_page_opens(self):
        """月次勤怠画面を表示できる。"""

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "自分の勤怠")
        self.assertContains(response, "日別の勤務記録")

    def test_02_selected_month_is_displayed(self):
        """指定した月の記録を表示できる。"""

        response = self.client.get(
            self.url,
            {"month": "2026-09"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2026年9月")

    def test_03_desktop_and_mobile_layouts_exist(self):
        """PC用とスマートフォン用の表示領域がある。"""

        response = self.client.get(
            self.url,
            {"month": "2026-09"},
        )

        self.assertContains(response, "e02-desktop-table")
        self.assertContains(response, "e02-mobile-list")

    def test_04_completed_days_from_database(self):
        """勤務完了日数が実データから取得される。"""

        jst = ZoneInfo("Asia/Tokyo")

        WorkSession.objects.create(
            employee=self.employee,
            work_date=date(2026, 9, 15),
            clock_in_at=datetime(
                2026,
                9,
                15,
                9,
                0,
                tzinfo=jst,
            ),
            clock_out_at=datetime(
                2026,
                9,
                15,
                18,
                0,
                tzinfo=jst,
            ),
            status=WorkSession.Status.COMPLETED,
        )

        response = self.client.get(
            self.url,
            {"month": "2026-09"},
        )

        self.assertEqual(
            response.context["completed_work_days"],
            1,
        )

    def test_05_invalid_month_is_rejected(self):
        """不正な対象月を拒否する。"""

        response = self.client.get(
            self.url,
            {"month": "invalid-month"},
        )

        self.assertEqual(response.status_code, 400)

    def test_06_pagination_works(self):
        """日別記録をページ切替できる。"""

        response = self.client.get(
            self.url,
            {
                "month": "2026-09",
                "page": "2",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.context["page_obj"].number,
            2,
        )


# E03 日別詳細
"""E03 日別詳細・修正申請のUIテスト。"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from attendance.models import MonthlyClosing, WorkSession
from corrections.models import CorrectionRequest


class E03UiTests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.employee = Employee.objects.create_user(
            employee_number="99301",
            password="E03EmployeeTest_2026!",
            first_name="一般",
            last_name="社員",
        )

        self.manager = Employee.objects.create_user(
            employee_number="99302",
            password="E03ManagerTest_2026!",
            first_name="管理",
            last_name="担当",
            is_business_admin=True,
        )

        self.work_day = date(2026, 10, 27)
        self.jst = ZoneInfo("Asia/Tokyo")

        self.url = reverse(
            "attendance:daily",
            args=[2026, 10, 27],
        )

        self.client.force_login(self.employee)

    def create_session(self):
        return WorkSession.objects.create(
            employee=self.employee,
            work_date=self.work_day,
            clock_in_at=datetime(
                2026,
                10,
                27,
                9,
                0,
                tzinfo=self.jst,
            ),
            clock_out_at=datetime(
                2026,
                10,
                27,
                18,
                0,
                tzinfo=self.jst,
            ),
            status=WorkSession.Status.COMPLETED,
        )

    def create_pending(self):
        session = self.create_session()

        correction = CorrectionRequest.objects.create(
            work_session=session,
            requested_by=self.employee,
            original_version=session.version,
            proposal={},
            reason="退勤時刻の確認",
            status=CorrectionRequest.Status.PENDING,
        )

        return correction

    def test_01_no_record_daily_opens(self):
        """勤務記録がない日も詳細を表示できる。"""

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "日別勤怠詳細")
        self.assertContains(response, "記録なし")
        self.assertContains(response, "原打刻の記録")

    def test_02_effective_record_display(self):
        """勤務記録がある場合、有効値を表示する。"""

        self.create_session()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "現在の有効値")
        self.assertContains(response, "09:00")
        self.assertContains(response, "18:00")

    def test_03_pending_disables_new_request(self):
        """審査中は新しい申請ボタンを表示しない。"""

        correction = self.create_pending()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "申請中の内容を確認する",
        )

        self.assertNotContains(
            response,
            "この日の修正を申請する",
        )

        self.assertContains(
            response,
            reverse(
                "corrections:detail",
                args=[correction.pk],
            ),
        )

    def test_04_create_form_opens(self):
        """修正申請フォームを表示できる。"""

        response = self.client.get(
            reverse(
                "corrections:create",
                args=[2026, 10, 27],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "修正を申請")
        self.assertContains(response, "breaks-TOTAL_FORMS")

    def test_05_pending_detail_has_withdraw_form(self):
        """自分の審査中申請に取下げフォームがある。"""

        correction = self.create_pending()

        response = self.client.get(
            reverse(
                "corrections:detail",
                args=[correction.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "申請を取り下げる",
        )

        self.assertContains(
            response,
            reverse(
                "corrections:withdraw",
                args=[correction.pk],
            ),
        )

    def test_06_other_users_correction_hidden(self):
        """他社員の申請詳細を表示しない。"""

        correction = self.create_pending()

        Employee = get_user_model()

        other = Employee.objects.create_user(
            employee_number="99303",
            password="E03OtherEmployee_2026!",
        )

        self.client.force_login(other)

        response = self.client.get(
            reverse(
                "corrections:detail",
                args=[correction.pk],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_07_future_day_disables_request(self):
        """未来の勤務日からは申請開始できない。"""

        response = self.client.get(
            reverse(
                "attendance:daily",
                args=[2099, 1, 10],
            )
        )

        self.assertEqual(response.status_code, 200)

        self.assertNotContains(
            response,
            "この日の修正を申請する",
        )

    def test_08_finalized_month_disables_request(self):
        """月次確定済みなら申請開始ボタンを表示しない。"""

        self.create_session()

        MonthlyClosing.objects.create(
            employee=self.employee,
            target_month=date(2026, 10, 1),
            status=MonthlyClosing.Status.FINALIZED,
            finalized_by=self.manager,
            finalized_at=timezone.now(),
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "月次確定済み")

        self.assertNotContains(
            response,
            "この日の修正を申請する",
        )


from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from attendance.chart_data import (
    build_work_hours_chart,
    build_incomplete_count_chart,
    format_seconds,
)
from attendance.models import WorkSession


class F11ChartTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        Employee = get_user_model()

        cls.employee = Employee.objects.create_user(
            employee_number="99801",
            password="TestPassword_2026!",
        )

        cls.month = date(2026, 11, 1)

    def test_no_record_is_null(self):
        data = build_work_hours_chart(
            self.employee,
            self.month,
        )

        self.assertIsNone(data["rows"][0]["value"])

    def test_zero_is_not_missing(self):
        self.assertEqual(
            format_seconds(0),
            "0時間00分",
        )

        self.assertEqual(
            format_seconds(None),
            "—",
        )

    def test_incomplete_count(self):
        WorkSession.objects.create(
            employee=self.employee,
            work_date=date(2026, 11, 5),
            status=WorkSession.Status.WORKING,
        )

        data = build_incomplete_count_chart(
            self.month,
            [self.employee.pk],
        )

        self.assertEqual(
            data["rows"][4]["value"],
            1,
        )


# ==========================================
# F11: Chart.js用データのテスト
# ==========================================

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from attendance.chart_data import (
    month_bounds,
    iter_month_days,
    work_result,
)
from attendance.models import WorkSession


class F11ChartUnitTests(SimpleTestCase):

    def test_month_bounds(self):
        """対象月の範囲を確認。"""

        start, end = month_bounds(date(2026, 11, 1))

        self.assertEqual(
            start,
            date(2026, 11, 1),
        )

        self.assertEqual(
            end,
            date(2026, 12, 1),
        )

    def test_december_next_year(self):
        """12月の翌月は翌年1月。"""

        _, end = month_bounds(date(2026, 12, 1))

        self.assertEqual(
            end,
            date(2027, 1, 1),
        )

    def test_leap_year(self):
        """うるう年の2月は29日。"""

        days = list(iter_month_days(date(2028, 2, 1)))

        self.assertEqual(len(days), 29)

    def test_no_record(self):
        """勤務記録なしはNone。"""

        status, seconds = work_result(
            None,
            [],
        )

        self.assertEqual(
            status,
            "記録なし",
        )
        self.assertIsNone(seconds)

    def test_incomplete(self):
        """出勤中は未完了。"""

        session = SimpleNamespace(status=WorkSession.Status.WORKING)

        status, seconds = work_result(
            session,
            [],
        )

        self.assertEqual(
            status,
            "未完了",
        )
        self.assertIsNone(seconds)

    @patch("attendance.chart_data.calculate_duration")
    def test_completed_eight_hours(self, mock_calc):
        """完了勤務の8時間を確認。"""

        mock_calc.return_value = SimpleNamespace(
            complete=True,
            work_seconds=28800,
        )

        session = SimpleNamespace(status=WorkSession.Status.COMPLETED)

        status, seconds = work_result(
            session,
            [],
        )

        self.assertEqual(status, "完了")
        self.assertEqual(seconds, 28800)

    @patch("attendance.chart_data.calculate_duration")
    def test_completed_zero_seconds(self, mock_calc):
        """0秒を記録なしと区別する。"""

        mock_calc.return_value = SimpleNamespace(
            complete=True,
            work_seconds=0,
        )

        session = SimpleNamespace(status=WorkSession.Status.COMPLETED)

        status, seconds = work_result(
            session,
            [],
        )

        self.assertEqual(status, "完了")
        self.assertEqual(seconds, 0)

    @patch("attendance.chart_data.calculate_duration")
    def test_invalid_completed_record(self, mock_calc):
        """不整合な勤務は未完了として扱う。"""

        mock_calc.return_value = SimpleNamespace(
            complete=False,
            work_seconds=None,
        )

        session = SimpleNamespace(status=WorkSession.Status.COMPLETED)

        status, seconds = work_result(
            session,
            [],
        )

        self.assertEqual(status, "未完了")
        self.assertIsNone(seconds)


# v1.4.3 規則の回帰試験

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
