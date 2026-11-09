"""A03 社員管理の一覧・検索・権限制御テスト。"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from management.models import EmploymentInfo
from management.templatetags.a03_directory import (
    a03_directory,
)


class A03EmployeeDirectoryTests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.manager = Employee.objects.create_user(
            employee_number="99501",
            password="A03ManagerTest_2026!",
            first_name="管理",
            last_name="担当",
            is_business_admin=True,
        )

        self.employee = Employee.objects.create_user(
            employee_number="99502",
            password="A03EmployeeTest_2026!",
            first_name="花子",
            last_name="山田",
        )

        self.inactive = Employee.objects.create_user(
            employee_number="99503",
            password="A03InactiveTest_2026!",
            first_name="退職",
            last_name="社員",
            is_active=False,
        )

        self.factory = RequestFactory()
        self.url = reverse("management:employee_list")

        self.client.force_login(self.manager)

    def snapshot(self, user=None, **params):
        """一覧画面用のデータを取得。"""

        request = self.factory.get(
            self.url,
            params,
        )

        request.user = user if user is not None else self.manager

        return a03_directory(
            {
                "request": request,
            }
        )

    def test_01_manager_can_open_employee_list(self):
        """業務管理者が社員一覧を表示できる。"""

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "社員一覧",
        )

        self.assertContains(
            response,
            "a03-summary-grid",
        )

    def test_02_search_employee_number(self):
        """社員番号による検索。"""

        result = self.snapshot(
            q="99502",
        )

        self.assertEqual(
            result["total_count"],
            1,
        )

        self.assertEqual(
            result["rows"][0]["employee"].pk,
            self.employee.pk,
        )

    def test_03_search_employee_name(self):
        """氏名による検索。"""

        result = self.snapshot(
            q="山田",
        )

        self.assertEqual(
            result["total_count"],
            1,
        )

        self.assertEqual(
            result["rows"][0]["employee"].pk,
            self.employee.pk,
        )

    def test_04_inactive_employee_filter(self):
        """無効アカウントを検索できる。"""

        result = self.snapshot(
            status="inactive",
        )

        self.assertEqual(
            result["total_count"],
            1,
        )

        self.assertFalse(
            result["rows"][0]["is_active"],
        )

    def test_05_business_admin_filter(self):
        """業務管理者だけを表示できる。"""

        result = self.snapshot(
            role="business_admin",
        )

        self.assertEqual(
            result["total_count"],
            1,
        )

        self.assertEqual(
            result["rows"][0]["employee"].pk,
            self.manager.pk,
        )

    def test_06_department_filter(self):
        """部署による絞り込み。"""

        EmploymentInfo.objects.create(
            employee=self.employee,
            department="開発部",
            hire_date=date(2026, 4, 1),
        )

        result = self.snapshot(
            department="開発部",
        )

        self.assertEqual(
            result["total_count"],
            1,
        )

        self.assertEqual(
            result["rows"][0]["department"],
            "開発部",
        )

    def test_07_employee_cannot_read_directory(self):
        """一般社員に全社員情報を渡さない。"""

        result = self.snapshot(
            user=self.employee,
        )

        self.assertFalse(
            result["allowed"],
        )

        # 実際のURLでも業務管理者権限を確認
        self.client.force_login(self.employee)

        response = self.client.get(self.url)

        self.assertIn(
            response.status_code,
            (302, 403),
        )

    def test_08_edit_links_exist(self):
        """既存の編集画面への導線がある。"""

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            reverse(
                "management:employee_edit",
                args=[self.employee.pk],
            ),
        )

        self.assertContains(
            response,
            reverse(
                "management:employment_edit",
                args=[self.employee.pk],
            ),
        )
