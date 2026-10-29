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
