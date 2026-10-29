from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class CommonLayoutTests(TestCase):
    """Phase 4の共通レイアウトテスト。"""

    def setUp(self):
        Employee = get_user_model()

        self.employee = Employee.objects.create_user(
            employee_number="91001",
            password="UiTestPassword_2026!",
            last_name="テスト",
            first_name="社員",
        )

        self.manager = Employee.objects.create_user(
            employee_number="91002",
            password="UiTestPassword_2026!",
            last_name="テスト",
            first_name="管理者",
            is_business_admin=True,
        )

    def test_login_page_without_navigation(self):
        """未ログインでは業務用ナビを表示しない。"""

        response = self.client.get(reverse("accounts:login"))

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertNotContains(
            response,
            'class="app-shell"',
        )

    def test_employee_page_has_sidebar(self):
        """社員ホームに最新版の共通レイアウトを表示する。"""

        self.client.force_login(self.employee)

        response = self.client.get(reverse("attendance:home"))

        self.assertEqual(
            response.status_code,
            200,
        )

        # 最新版の共通レイアウト
        self.assertContains(
            response,
            'class="app-frame"',
        )

        # PC用サイドバー
        self.assertContains(
            response,
            'class="app-side"',
        )

        # 社員用メニュー
        self.assertContains(
            response,
            'aria-label="社員メニュー"',
        )

        # 打刻画面へのリンク
        self.assertContains(
            response,
            'href="/employee/"',
        )

    def test_employee_has_no_admin_link(self):
        """一般社員に管理者画面へのリンクを表示しない。"""

        self.client.force_login(self.employee)

        response = self.client.get(reverse("attendance:home"))

        self.assertEqual(response.status_code, 200)

        # 一般社員には管理画面へのリンクを表示しない
        self.assertNotContains(
            response,
            f'href="{reverse("management:home")}"',
        )

    def test_manager_can_see_admin_link(self):
        """管理者に管理者画面へのリンクを表示する。"""

        self.client.force_login(self.manager)

        response = self.client.get(reverse("attendance:home"))

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            f'href="{reverse("management:home")}"',
        )

    def test_management_page(self):
        """管理者ホームに管理者用UIを表示する。"""

        self.client.force_login(self.manager)

        response = self.client.get(reverse("management:home"))

        self.assertEqual(response.status_code, 200)

        # 最新デザインのPC用サイドバー
        self.assertContains(
            response,
            'class="app-side"',
        )

        # 管理者用のナビゲーション
        self.assertContains(
            response,
            'aria-label="管理者メニュー"',
        )

        # 管理者ホーム
        self.assertContains(
            response,
            "管理者ホーム",
        )

    def test_employee_cannot_open_management(self):
        """一般社員が管理URLへアクセスすると403。"""

        self.client.force_login(self.employee)

        response = self.client.get(reverse("management:home"))

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_mobile_navigation_in_html(self):
        """スマートフォン用ナビがHTMLに存在する。"""

        self.client.force_login(self.manager)

        response = self.client.get(reverse("attendance:home"))

        self.assertContains(
            response,
            'aria-label="スマートフォン用メニュー"',
        )

    def test_forced_password_change_hides_shell(self):
        """初回変更が必要な社員には業務UIを表示しない。"""

        self.employee.must_change_password = True
        self.employee.save(update_fields=["must_change_password"])

        self.client.force_login(self.employee)

        response = self.client.get(reverse("accounts:password_change"))

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertNotContains(
            response,
            'class="app-shell"',
        )
