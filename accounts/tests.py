

# 認証・アカウント

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

        self.assertRedirects(response, reverse("management:attendance_list"))

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

    def _issue_initial_password(self, hours_left):
        from datetime import timedelta
        from django.utils import timezone

        self.employee.must_change_password = True
        self.employee.initial_password_issued_at = timezone.now() - timedelta(hours=72 - hours_left)
        self.employee.initial_password_expires_at = timezone.now() + timedelta(hours=hours_left)
        self.employee.save()

    def test_initial_password_within_72_hours_only_allows_password_change(self):
        """T10・15章: 初回変更前は業務画面とAPIを利用できず、変更画面へ案内する。"""
        self._issue_initial_password(hours_left=1)
        response = self.client.post(reverse("accounts:login"), {"username": "90001", "password": self.password})
        self.assertRedirects(response, reverse("accounts:password_change"), fetch_redirect_response=False)
        self.assertRedirects(
            self.client.get(reverse("attendance:home")),
            reverse("accounts:password_change"), fetch_redirect_response=False,
        )
        self.assertEqual(
            self.client.get(reverse("notifications:panel"), HTTP_ACCEPT="application/json").status_code, 302,
        )
        self.assertEqual(self.client.post(reverse("attendance:clock_action")).status_code, 403)

    def test_expired_initial_password_cannot_log_in(self):
        """T10: 発行から72時間に達した初期パスワードではログインできない。"""
        self._issue_initial_password(hours_left=-1)
        response = self.client.post(reverse("accounts:login"), {"username": "90001", "password": self.password})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "初期パスワードの有効期限が切れています。")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_session_is_ended_when_initial_password_expires_before_change(self):
        """T10: 期限到達後は表示・保存のどちらでもログアウトし、変更を保存しない。"""
        from datetime import timedelta
        from django.utils import timezone

        self._issue_initial_password(hours_left=1)
        self.client.force_login(self.employee)
        type(self.employee).objects.filter(pk=self.employee.pk).update(
            initial_password_expires_at=timezone.now() - timedelta(seconds=1),
        )
        response = self.client.post(
            reverse("accounts:password_change"),
            {"old_password": self.password, "new_password1": "NewPassword_2026!x", "new_password2": "NewPassword_2026!x"},
        )
        self.assertRedirects(response, reverse("accounts:login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.check_password(self.password))
        self.assertTrue(self.employee.must_change_password)

    def test_reactivation_does_not_revive_session_from_before_deactivation(self):
        """T01: 停止前のセッションは再有効化後も利用できない。"""
        from django.test import Client

        other_client = Client()
        other_client.force_login(self.manager)
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse("attendance:home")).status_code, 200)

        self.employee.is_active = False
        self.employee.save()
        self.employee.is_active = True
        self.employee.save()

        response = self.client.get(reverse("attendance:home"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("accounts:login")))
        # 他の社員のセッションには影響しない。
        self.assertEqual(other_client.get(reverse("attendance:home")).status_code, 200)

        # 再有効化後に改めてログインすれば利用できる。
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse("attendance:home")).status_code, 200)


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


# 初期パスワード・再発行
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class Phase8AccountTests(TestCase):
    """アカウント情報・使い方ガイドのテスト。"""

    def setUp(self):
        Employee = get_user_model()

        self.employee = Employee.objects.create_user(
            employee_number="83001",
            password="Phase8Employee_2026!",
            first_name="花子",
            last_name="山田",
        )

        self.other = Employee.objects.create_user(
            employee_number="83002",
            password="Phase8Other_2026!",
            first_name="太郎",
            last_name="佐藤",
        )

        self.manager = Employee.objects.create_user(
            employee_number="83003",
            password="Phase8Manager_2026!",
            first_name="一郎",
            last_name="田中",
            is_business_admin=True,
        )

    def test_employee_overview_opens(self):
        """社員のアカウント画面を表示できる。"""

        self.client.force_login(self.employee)

        response = self.client.get(reverse("accounts:overview"))

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            "アカウントと使い方",
        )

    def test_employee_information_is_displayed(self):
        """本人の社員情報を表示する。"""

        self.client.force_login(self.employee)

        response = self.client.get(reverse("accounts:overview"))

        self.assertContains(
            response,
            self.employee.employee_number,
        )

        self.assertContains(
            response,
            "山田",
        )

        self.assertContains(
            response,
            "花子",
        )

    def test_other_employee_is_not_displayed(self):
        """別の社員の情報を表示しない。"""

        self.client.force_login(self.employee)

        response = self.client.get(reverse("accounts:overview"))

        self.assertNotContains(
            response,
            self.other.employee_number,
        )

        self.assertNotContains(
            response,
            "佐藤",
        )

    def test_regular_employee_role(self):
        """一般社員は一般社員として表示される。"""

        self.client.force_login(self.employee)

        response = self.client.get(reverse("accounts:overview"))

        self.assertContains(
            response,
            "一般社員",
        )

        self.assertNotContains(
            response,
            "管理者権限あり",
        )

    def test_business_admin_role(self):
        """業務管理者の権限を正しく表示する。"""

        self.assertTrue(self.manager.is_business_admin)

        # 業務管理者とDjango管理サイト権限は別
        self.assertFalse(self.manager.is_staff)

        self.client.force_login(self.manager)

        response = self.client.get(reverse("accounts:overview"))

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            "管理者権限あり",
        )

    def test_password_change_link(self):
        """既存のパスワード変更画面へ移動できる。"""

        self.client.force_login(self.employee)

        response = self.client.get(reverse("accounts:overview"))

        self.assertContains(
            response,
            reverse("accounts:password_change"),
        )

    def test_guide_page_opens(self):
        """使い方ガイドを表示できる。"""

        self.client.force_login(self.employee)

        response = self.client.get(reverse("accounts:guide"))

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            "使い方ガイド",
        )

    def test_guide_explains_existing_features(self):
        """Phase 5〜7の主要機能を説明している。"""

        self.client.force_login(self.employee)

        response = self.client.get(reverse("accounts:guide"))

        for text in (
            "休憩開始",
            "休憩終了",
            "自分の勤怠",
            "記録なし",
            "修正申請",
            "取下げ",
            "500文字以内",
        ):
            with self.subTest(text=text):
                self.assertContains(
                    response,
                    text,
                )

    def test_sidebar_has_account_link(self):
        """共通メニューにアカウントへのリンクがある。"""

        self.client.force_login(self.employee)

        response = self.client.get(reverse("attendance:home"))

        self.assertContains(
            response,
            reverse("accounts:overview"),
        )

    def test_anonymous_access_is_blocked(self):
        """未ログインではアカウント情報を見られない。"""

        response = self.client.get(reverse("accounts:overview"))

        self.assertEqual(
            response.status_code,
            302,
        )

        response = self.client.get(reverse("accounts:guide"))

        self.assertEqual(
            response.status_code,
            302,
        )

    def test_pages_are_read_only(self):
        """POSTでアカウント情報を変更できない。"""

        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("accounts:overview"),
            {
                "employee_number": "99999",
                "is_business_admin": "true",
            },
        )

        self.assertEqual(
            response.status_code,
            405,
        )

        response = self.client.post(
            reverse("accounts:guide"),
            {},
        )

        self.assertEqual(
            response.status_code,
            405,
        )

        self.employee.refresh_from_db()

        self.assertEqual(
            self.employee.employee_number,
            "83001",
        )

        self.assertFalse(self.employee.is_business_admin)

    def test_password_hash_is_not_rendered(self):
        """パスワードのハッシュをHTMLへ表示しない。"""

        self.client.force_login(self.employee)

        response = self.client.get(reverse("accounts:overview"))

        self.assertNotContains(
            response,
            self.employee.password,
        )
