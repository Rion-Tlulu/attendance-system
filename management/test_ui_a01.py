"""A01 管理者勤怠一覧の表示・集計テスト。"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from attendance.models import MonthlyClosing, WorkSession
from corrections.models import CorrectionRequest
from management.templatetags.a01_dashboard import (
    a01_snapshot,
)


class A01ManagerAttendanceUiTests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.manager = Employee.objects.create_user(
            employee_number="99401",
            password="A01ManagerTest_2026!",
            first_name="管理",
            last_name="担当",
            is_business_admin=True,
        )

        self.employee = Employee.objects.create_user(
            employee_number="99402",
            password="A01EmployeeTest_2026!",
            first_name="花子",
            last_name="山田",
        )

        self.factory = RequestFactory()
        self.month = date(2026, 11, 1)

        self.client.force_login(self.manager)

    def snapshot(self, **params):
        """対象月でA01の集計を取得する。"""

        query = {
            "month": "2026-11",
            **params,
        }

        request = self.factory.get(
            "/management/attendance/",
            query,
        )

        request.user = self.manager

        return a01_snapshot(
            {
                "request": request,
            }
        )

    def test_01_manager_can_open_page(self):
        """管理者は勤怠一覧を閲覧できる。"""

        response = self.client.get("/management/attendance/")

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            "管理者｜勤怠一覧",
        )

        self.assertContains(
            response,
            "社員別の勤怠状況",
        )

    def test_02_employee_search(self):
        """社員番号で絞り込みできる。"""

        result = self.snapshot(
            q="99402",
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(
            result["employee_count"],
            1,
        )

        rows = list(result["page_obj"].object_list)

        self.assertEqual(
            rows[0]["employee"].pk,
            self.employee.pk,
        )

    def test_03_no_record_is_not_absence(self):
        """勤務記録がない社員を欠勤扱いしない。"""

        result = self.snapshot(
            q="99402",
        )

        row = list(result["page_obj"].object_list)[0]

        self.assertEqual(
            row["incomplete"],
            0,
        )

        self.assertEqual(
            row["status_label"],
            "記録なし",
        )

    def test_04_incomplete_session(self):
        """勤務中の記録を未完了として集計する。"""

        WorkSession.objects.create(
            employee=self.employee,
            work_date=date(2026, 11, 5),
            clock_in_at=timezone.now(),
            status=WorkSession.Status.WORKING,
        )

        result = self.snapshot(
            q="99402",
        )

        self.assertEqual(
            result["incomplete_count"],
            1,
        )

        row = list(result["page_obj"].object_list)[0]

        self.assertEqual(
            row["status_label"],
            "未完了あり",
        )

    def test_05_pending_correction(self):
        """審査待ち申請の件数を表示する。"""

        session = WorkSession.objects.create(
            employee=self.employee,
            work_date=date(2026, 11, 5),
            clock_in_at=timezone.now(),
            status=WorkSession.Status.WORKING,
        )

        CorrectionRequest.objects.create(
            work_session=session,
            requested_by=self.employee,
            original_version=session.version,
            proposal={},
            reason="勤務時刻の修正",
            status=CorrectionRequest.Status.PENDING,
        )

        result = self.snapshot(
            q="99402",
            status="pending",
        )

        self.assertEqual(
            result["employee_count"],
            1,
        )

        self.assertEqual(
            result["pending_count"],
            1,
        )

    def test_06_finalized_month(self):
        """月次確定済み社員を正しく集計する。"""

        MonthlyClosing.objects.create(
            employee=self.employee,
            target_month=self.month,
            status=MonthlyClosing.Status.FINALIZED,
            finalized_by=self.manager,
            finalized_at=timezone.now(),
        )

        result = self.snapshot(
            q="99402",
            status="finalized",
        )

        self.assertEqual(
            result["employee_count"],
            1,
        )

        self.assertEqual(
            result["finalized_count"],
            1,
        )

    def test_07_normal_employee_cannot_read_snapshot(self):
        """一般社員には全社員データを渡さない。"""

        request = self.factory.get(
            "/management/attendance/",
            {"month": "2026-11"},
        )

        request.user = self.employee

        result = a01_snapshot(
            {
                "request": request,
            }
        )

        self.assertFalse(result["allowed"])

    def test_08_invalid_month_is_reported(self):
        """不正な対象月を正常値として扱わない。"""

        result = self.snapshot(
            month="invalid",
        )

        self.assertTrue(result["month_error"])
