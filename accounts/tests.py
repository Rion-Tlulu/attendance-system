
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(AXES_ENABLED=False)
class AuthenticationFlowTests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.password = "TestPassword_2026!"

        self.employee = Employee.objects.create_user(
            employee_number="90001",
            password=self.password,
            first_name="社員",
            last_name="テスト",
        )

        self.manager = Employee.objects.create_user(
            employee_number="90002",
            password=self.password,
            first_name="管理者",
            last_name="テスト",
            is_business_admin=True,
        )

    def test_successful_login(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "90001",
                "password": self.password,
            },
        )

        self.assertRedirects(
            response,
            reverse("attendance:home"),
        )

    def test_anonymous_cannot_access_home(self):
        response = self.client.get(
            reverse("attendance:home")
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse("accounts:login"),
            response.url,
        )

    def test_employee_cannot_access_management(self):
        self.client.force_login(self.employee)

        response = self.client.get(
            reverse("management:home")
        )

        self.assertEqual(response.status_code, 403)

    def test_manager_can_access_management(self):
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse("management:home")
        )

        self.assertEqual(response.status_code, 200)

    def test_first_login_requires_password_change(self):
        self.employee.must_change_password = True
        self.employee.save(
            update_fields=["must_change_password"]
        )

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "90001",
                "password": self.password,
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:password_change"),
        )

        response = self.client.get(
            reverse("attendance:home")
        )

        self.assertRedirects(
            response,
            reverse("accounts:password_change"),
        )

        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": self.password,
                "new_password1": "AnotherStrong_2026!",
                "new_password2": "AnotherStrong_2026!",
            },
        )

        self.assertRedirects(
            response,
            reverse("attendance:home"),
        )

        self.employee.refresh_from_db()

        self.assertFalse(
            self.employee.must_change_password
        )

        self.assertTrue(
            self.employee.check_password(
                "AnotherStrong_2026!"
            )
        )

    def test_inactive_user_cannot_login(self):
        self.employee.is_active = False
        self.employee.save(
            update_fields=["is_active"]
        )

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "90001",
                "password": self.password,
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            "_auth_user_id" in self.client.session
        )

    def test_logout_requires_post(self):
        self.client.force_login(self.employee)

        response = self.client.get(
            reverse("accounts:logout")
        )

        self.assertEqual(response.status_code, 405)

    def test_logout_success(self):
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("accounts:logout")
        )

        self.assertRedirects(
            response,
            reverse("accounts:login"),
        )


class LoginRateLimitTests(TestCase):
    """ログイン試行回数制限を確認する。"""

    def setUp(self):
        Employee = get_user_model()

        Employee.objects.create_user(
            employee_number="90003",
            password="RateLimitTest_2026!",
        )

    def test_lockout_after_five_failures(self):
        login_url = reverse("accounts:login")

        for _ in range(5):
            self.client.post(
                login_url,
                {
                    "username": "90003",
                    "password": "IncorrectPassword",
                },
            )

        response = self.client.post(
            login_url,
            {
                "username": "90003",
                "password": "RateLimitTest_2026!",
            },
        )

        self.assertEqual(
            response.status_code,
            429,
        )
