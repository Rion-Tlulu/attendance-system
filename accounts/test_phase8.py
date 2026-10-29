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
