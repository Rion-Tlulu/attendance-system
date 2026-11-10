

# ---- management/tests.py ----
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


# ---- management/test_phase9.py ----
import uuid

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from attendance.models import (
    ClockEvent,
    MonthlyClosing,
    WorkSession,
)
from auditlog.models import AuditLog
from corrections.models import CorrectionRequest
from corrections.services import current_values


class Phase9Tests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.manager = Employee.objects.create_user(
            employee_number="94001",
            password="ManagerPhase9_2026!",
            first_name="管理",
            last_name="担当",
            is_business_admin=True,
        )

        self.other_manager = Employee.objects.create_user(
            employee_number="94002",
            password="OtherManagerPhase9_2026!",
            first_name="別の",
            last_name="管理者",
            is_business_admin=True,
        )

        self.employee = Employee.objects.create_user(
            employee_number="94003",
            password="EmployeePhase9_2026!",
            first_name="社員",
            last_name="テスト",
        )

        self.day = date(2026, 9, 15)
        self.jst = ZoneInfo("Asia/Tokyo")

        self.work = WorkSession.objects.create(
            employee=self.employee,
            work_date=self.day,
            clock_in_at=self.dt(9),
            clock_out_at=self.dt(18),
            status=WorkSession.Status.COMPLETED,
        )

    def dt(self, hour, minute=0):
        return datetime(
            2026,
            9,
            15,
            hour,
            minute,
            tzinfo=self.jst,
        )

    def create_request(self, work=None):
        work = work or self.work

        proposal = current_values(work)

        proposal["clock_out_at"] = "2026-09-15T18:30:00+09:00"

        return CorrectionRequest.objects.create(
            work_session=work,
            requested_by=work.employee,
            original_version=work.version,
            proposal=proposal,
            reason="退勤時刻を修正するため",
            status=CorrectionRequest.Status.PENDING,
        )

    def test_anonymous_admin_access_redirected(self):
        response = self.client.post(reverse("management:attendance_list"))

        self.assertEqual(response.status_code, 302)

    def test_employee_cannot_open_admin_list(self):
        self.client.force_login(self.employee)

        for name in (
            "management:attendance_list",
            "management:corrections",
            "management:employees",
            "management:audit_history",
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 403)

    def test_staff_flag_alone_is_not_business_admin(self):
        self.employee.is_staff = True
        self.employee.save(update_fields=["is_staff"])

        self.client.force_login(self.employee)

        response = self.client.get(reverse("management:attendance_list"))

        self.assertEqual(response.status_code, 403)

    def test_manager_can_open_attendance_list(self):
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse("management:attendance_list"),
            {"month": "2026-09"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "勤怠一覧")

    def test_manager_can_open_employee_month(self):
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse(
                "management:employee_month",
                args=[self.employee.pk, 2026, 9],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "月次勤怠詳細")

    def test_approve_updates_effective_values(self):
        correction = self.create_request()

        event = ClockEvent.objects.create(
            work_session=self.work,
            kind=ClockEvent.Kind.CLOCK_OUT,
            recorded_at=self.dt(18),
            operation_id=uuid.uuid4(),
        )

        self.client.force_login(self.manager)

        response = self.client.post(
            reverse(
                "management:correction_review",
                args=[correction.pk],
            ),
            {"action": "approve", "return_reason": ""},
        )

        self.assertEqual(response.status_code, 302)

        correction.refresh_from_db()
        self.work.refresh_from_db()
        event.refresh_from_db()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.APPROVED,
        )

        self.assertEqual(
            self.work.clock_out_at,
            self.dt(18, 30),
        )

        # 原打刻は変更されない
        self.assertEqual(event.recorded_at, self.dt(18))

        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.CORRECTION_APPROVE,
            ).exists()
        )

    def test_return_does_not_update_effective_values(self):
        correction = self.create_request()

        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:correction_review",
                args=[correction.pk],
            ),
            {
                "action": "return",
                "return_reason": "申請内容を確認してください。",
            },
        )

        correction.refresh_from_db()
        self.work.refresh_from_db()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.RETURNED,
        )

        self.assertEqual(
            self.work.clock_out_at,
            self.dt(18),
        )

    def test_self_approval_is_blocked(self):
        own_work = WorkSession.objects.create(
            employee=self.manager,
            work_date=self.day,
            clock_in_at=self.dt(9),
            clock_out_at=self.dt(18),
            status=WorkSession.Status.COMPLETED,
        )

        correction = self.create_request(own_work)

        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:correction_review",
                args=[correction.pk],
            ),
            {"action": "approve", "return_reason": ""},
        )

        correction.refresh_from_db()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.PENDING,
        )

    def test_stale_correction_is_blocked(self):
        correction = self.create_request()

        self.work.version += 1
        self.work.save(update_fields=["version"])

        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:correction_review",
                args=[correction.pk],
            ),
            {"action": "approve", "return_reason": ""},
        )

        correction.refresh_from_db()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.PENDING,
        )

    def test_pending_request_blocks_finalization(self):
        self.create_request()

        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:month_finalize",
                args=[self.employee.pk, 2026, 9],
            ),
            {"checked_no_record": "on"},
        )

        self.assertFalse(
            MonthlyClosing.objects.filter(
                employee=self.employee,
                target_month=date(2026, 9, 1),
                status=MonthlyClosing.Status.FINALIZED,
            ).exists()
        )

    def test_manager_cannot_finalize_own_month(self):
        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:month_finalize",
                args=[self.manager.pk, 2026, 9],
            ),
            {"checked_no_record": "on"},
        )

        self.assertFalse(
            MonthlyClosing.objects.filter(
                employee=self.manager,
                target_month=date(2026, 9, 1),
                status=MonthlyClosing.Status.FINALIZED,
            ).exists()
        )

    def test_finalization_requires_confirmation(self):
        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:month_finalize",
                args=[self.employee.pk, 2026, 9],
            ),
            {},
        )

        self.assertFalse(
            MonthlyClosing.objects.filter(
                employee=self.employee,
                target_month=date(2026, 9, 1),
                status=MonthlyClosing.Status.FINALIZED,
            ).exists()
        )

    def test_finalization_and_csv(self):
        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:month_finalize",
                args=[self.employee.pk, 2026, 9],
            ),
            {"checked_no_record": "on"},
        )

        self.assertTrue(
            MonthlyClosing.objects.filter(
                employee=self.employee,
                target_month=date(2026, 9, 1),
                status=MonthlyClosing.Status.FINALIZED,
            ).exists()
        )

        response = self.client.post(
            reverse(
                "management:month_csv",
                args=[self.employee.pk, 2026, 9],
            )
        )

        self.assertEqual(response.status_code, 200)

        # UTF-8 BOM
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))

        # CRLF
        self.assertIn(
            b"\r\n",
            response.content,
        )

    def test_unfinalized_month_csv_is_blocked(self):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse(
                "management:month_csv",
                args=[self.employee.pk, 2026, 9],
            )
        )

        self.assertEqual(response.status_code, 302)

    def test_regular_employee_cannot_download_csv(self):
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse(
                "management:month_csv",
                args=[self.employee.pk, 2026, 9],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_audit_history_is_admin_only(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("management:audit_history"))

        self.assertEqual(response.status_code, 200)

        self.client.force_login(self.employee)

        response = self.client.get(reverse("management:audit_history"))

        self.assertEqual(response.status_code, 403)

    def test_incomplete_work_blocks_finalization(self):
        """未完了の勤務がある月は確定できない。"""

        work_day = date(2026, 9, 16)

        WorkSession.objects.create(
            employee=self.employee,
            work_date=work_day,
            clock_in_at=datetime(
                2026,
                9,
                16,
                9,
                tzinfo=self.jst,
            ),
            status=WorkSession.Status.WORKING,
        )

        self.client.force_login(self.manager)

        self.client.post(
            reverse(
                "management:month_finalize",
                args=[self.employee.pk, 2026, 9],
            ),
            {"checked_no_record": "on"},
        )

        self.assertFalse(
            MonthlyClosing.objects.filter(
                employee=self.employee,
                target_month=date(2026, 9, 1),
                status=MonthlyClosing.Status.FINALIZED,
            ).exists()
        )

    def test_month_can_be_reopened(self):
        """確定済み月を未確定へ戻せる。"""

        closing = MonthlyClosing.objects.create(
            employee=self.employee,
            target_month=date(2026, 9, 1),
            status=MonthlyClosing.Status.FINALIZED,
            finalized_by=self.manager,
            finalized_at=self.dt(18),
        )

        self.client.force_login(self.manager)

        response = self.client.post(
            reverse(
                "management:month_reopen",
                args=[self.employee.pk, 2026, 9],
            ),
            {
                "reason": "勤務情報を再確認するため",
            },
        )

        self.assertEqual(response.status_code, 302)

        closing.refresh_from_db()

        self.assertNotEqual(
            closing.status,
            MonthlyClosing.Status.FINALIZED,
        )

        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.MONTH_REOPEN,
            ).exists()
        )


# ---- management/test_phase10.py ----
"""
Phase 10：勤怠管理システム最終回帰テスト。

確認対象：
- 業務管理者の権限
- 自己承認禁止
- 原打刻の保全
- 修正申請の状態遷移
- 月次確定の制限
- CSV出力
- CSRF保護
- 勤怠時間の計算
"""

import csv
import io
import uuid

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from attendance.models import (
    ClockEvent,
    WorkSession,
)
from attendance.reporting import build_monthly_report

from auditlog.models import AuditLog
from corrections.models import CorrectionRequest
from corrections.services import current_values

from management.services import (
    AdminActionError,
    finalize_month,
    review_correction,
)
from management.views import _csv_safe


class Phase10RegressionTests(TestCase):
    """Phase 10：権限・勤怠・監査の回帰テスト。"""

    def setUp(self):
        Employee = get_user_model()

        self.manager = Employee.objects.create_user(
            employee_number="95001",
            password="Phase10Manager_2026!",
            first_name="管理",
            last_name="担当",
            is_business_admin=True,
        )

        self.employee = Employee.objects.create_user(
            employee_number="95002",
            password="Phase10Employee_2026!",
            first_name="一般",
            last_name="社員",
        )

        self.other = Employee.objects.create_user(
            employee_number="95003",
            password="Phase10Other_2026!",
            first_name="別",
            last_name="社員",
        )

        self.day = date(2026, 9, 15)
        self.jst = ZoneInfo("Asia/Tokyo")

        self.work = self.create_work(
            self.employee,
            self.day,
        )

    # ======================================
    # テスト用共通処理
    # ======================================

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

    def create_work(self, employee, day):
        return WorkSession.objects.create(
            employee=employee,
            work_date=day,
            clock_in_at=self.dt(day, 9),
            clock_out_at=self.dt(day, 18),
            status=WorkSession.Status.COMPLETED,
        )

    def create_request(self, work=None):
        work = work or self.work

        proposal = current_values(work)

        proposal["clock_out_at"] = self.dt(
            work.work_date,
            18,
            30,
        ).isoformat(timespec="seconds")

        return CorrectionRequest.objects.create(
            work_session=work,
            requested_by=work.employee,
            original_version=work.version,
            proposal=proposal,
            reason="退勤時刻を修正するため",
            status=CorrectionRequest.Status.PENDING,
        )

    def review(self, correction, action="approve", reason=""):
        return review_correction(
            manager_id=self.manager.pk,
            correction_id=correction.pk,
            action=action,
            return_reason=reason,
        )

    def closing_kwargs(self, employee=None):
        employee = employee or self.employee

        return {
            "manager_id": self.manager.pk,
            "employee_id": employee.pk,
            "target_month": date(2026, 9, 1),
            "checked_no_record": True,
        }

    def csv_url(self):
        return reverse(
            "management:month_csv",
            args=[self.employee.pk, 2026, 9],
        )

    # ======================================
    # 1. 未ログインのアクセス拒否
    # ======================================

    def test_01_anonymous_admin_redirect(self):
        response = self.client.get(reverse("management:attendance_list"))

        self.assertEqual(response.status_code, 302)

    # ======================================
    # 2. is_staffだけでは管理者ではない
    # ======================================

    def test_02_staff_flag_not_business_admin(self):
        self.employee.is_staff = True
        self.employee.save(update_fields=["is_staff"])

        self.client.force_login(self.employee)

        response = self.client.get(reverse("management:attendance_list"))

        self.assertEqual(response.status_code, 403)

    # ======================================
    # 3. 一般社員は審査できない
    # ======================================

    def test_03_employee_cannot_review(self):
        correction = self.create_request()

        self.client.force_login(self.employee)

        response = self.client.post(
            reverse(
                "management:correction_review",
                args=[correction.pk],
            ),
            {
                "action": "approve",
                "return_reason": "",
            },
        )

        self.assertEqual(response.status_code, 403)

        correction.refresh_from_db()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.PENDING,
        )

    # ======================================
    # 4. 一般社員は他社員を編集できない
    # ======================================

    def test_04_employee_cannot_edit_staff(self):
        self.client.force_login(self.employee)

        response = self.client.get(
            reverse(
                "management:employee_edit",
                args=[self.other.pk],
            )
        )

        self.assertEqual(response.status_code, 403)

    # ======================================
    # 5. 一般社員はCSVを出力できない
    # ======================================

    def test_05_employee_cannot_export_csv(self):
        self.client.force_login(self.employee)

        response = self.client.post(self.csv_url())

        self.assertEqual(response.status_code, 403)

    # ======================================
    # 6. 管理者の自己承認を禁止
    # ======================================

    def test_06_manager_cannot_approve_self(self):
        own_work = self.create_work(
            self.manager,
            self.day,
        )

        correction = self.create_request(own_work)

        with self.assertRaises(AdminActionError):
            self.review(correction)

        correction.refresh_from_db()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.PENDING,
        )

    # ======================================
    # 7. 承認しても原打刻は変わらない
    # ======================================

    def test_07_original_clock_event_preserved(self):
        correction = self.create_request()

        event = ClockEvent.objects.create(
            work_session=self.work,
            kind=ClockEvent.Kind.CLOCK_OUT,
            recorded_at=self.dt(self.day, 18),
            operation_id=uuid.uuid4(),
        )

        self.review(correction)

        self.work.refresh_from_db()
        event.refresh_from_db()
        correction.refresh_from_db()

        self.assertEqual(
            self.work.clock_out_at,
            self.dt(self.day, 18, 30),
        )

        self.assertEqual(
            event.recorded_at,
            self.dt(self.day, 18),
        )

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.APPROVED,
        )

        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.Action.CORRECTION_APPROVE).exists()
        )

    # ======================================
    # 8. 二重承認禁止
    # ======================================

    def test_08_double_approval_blocked(self):
        correction = self.create_request()

        self.review(correction)

        with self.assertRaises(AdminActionError):
            self.review(correction)

        self.assertEqual(
            AuditLog.objects.filter(action=AuditLog.Action.CORRECTION_APPROVE).count(),
            1,
        )

    # ======================================
    # 9. 取下げ済み申請を承認できない
    # ======================================

    def test_09_withdrawn_request_blocked(self):
        correction = self.create_request()

        correction.status = CorrectionRequest.Status.WITHDRAWN
        correction.withdrawn_at = timezone.now()

        correction.save(update_fields=["status", "withdrawn_at"])

        with self.assertRaises(AdminActionError):
            self.review(correction)

    # ======================================
    # 10. 古い勤務データ版の申請を拒否
    # ======================================

    def test_10_stale_version_blocked(self):
        correction = self.create_request()

        self.work.version += 1
        self.work.save(update_fields=["version"])

        with self.assertRaises(AdminActionError):
            self.review(correction)

    # ======================================
    # 11. 差戻し時は勤務有効値を変更しない
    # ======================================

    def test_11_return_does_not_change_work(self):
        correction = self.create_request()

        original_end = self.work.clock_out_at

        self.review(
            correction,
            action="return",
            reason="退勤時刻の確認が必要です",
        )

        correction.refresh_from_db()
        self.work.refresh_from_db()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.RETURNED,
        )

        self.assertEqual(
            self.work.clock_out_at,
            original_end,
        )

    # ======================================
    # 12. 差戻し理由は必須
    # ======================================

    def test_12_return_reason_required(self):
        correction = self.create_request()

        with self.assertRaises(AdminActionError):
            self.review(
                correction,
                action="return",
                reason="",
            )

        correction.refresh_from_db()

        self.assertEqual(
            correction.status,
            CorrectionRequest.Status.PENDING,
        )

    # ======================================
    # 13. 審査中は月次確定できない
    # ======================================

    def test_13_pending_request_blocks_finalization(self):
        self.create_request()

        with self.assertRaises(AdminActionError):
            finalize_month(**self.closing_kwargs())

    # ======================================
    # 14. 勤務未完了は月次確定できない
    # ======================================

    def test_14_incomplete_work_blocks_finalization(self):
        another_day = date(2026, 9, 16)

        WorkSession.objects.create(
            employee=self.employee,
            work_date=another_day,
            clock_in_at=self.dt(another_day, 9),
            status=WorkSession.Status.WORKING,
        )

        with self.assertRaises(AdminActionError):
            finalize_month(**self.closing_kwargs())

    # ======================================
    # 15. 自分自身の月次確定は禁止
    # ======================================

    def test_15_manager_cannot_finalize_self(self):
        with self.assertRaises(AdminActionError):
            finalize_month(**self.closing_kwargs(self.manager))

    # ======================================
    # 16. 未確定月のCSVは禁止
    # ======================================

    def test_16_unfinalized_csv_blocked(self):
        self.client.force_login(self.manager)

        response = self.client.post(self.csv_url())

        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            AuditLog.objects.filter(action=AuditLog.Action.CSV_EXPORT).exists()
        )

    # ======================================
    # 17. CSVのGETアクセスを拒否
    # ======================================

    def test_17_csv_requires_post(self):
        self.client.force_login(self.manager)

        response = self.client.get(self.csv_url())

        self.assertEqual(response.status_code, 405)

    # ======================================
    # 18. 確定済みCSVと監査ログ
    # ======================================

    def test_18_finalized_csv_and_audit(self):
        finalize_month(**self.closing_kwargs())

        self.client.force_login(self.manager)

        response = self.client.post(self.csv_url())

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "text/csv",
            response["Content-Type"],
        )

        # UTF-8 BOM
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))

        # 改行はCRLF
        self.assertIn(
            b"\r\n",
            response.content,
        )

        # CSV出力の監査記録
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.CSV_EXPORT,
                actor=self.manager,
                target_employee=self.employee,
            ).exists()
        )

    def test_18_csv_header_matches_each_data_row(self):
        finalize_month(**self.closing_kwargs())
        self.client.force_login(self.manager)

        response = self.client.post(self.csv_url())
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(rows[0][8], "実働時間")
        self.assertTrue(all(len(row) == len(rows[0]) for row in rows[1:]))

    # ======================================
    # 19. CSV数式注入対策
    # ======================================

    def test_19_csv_formula_guard(self):
        samples = [
            "=1+1",
            "+1+1",
            "-1+1",
            "@SUM(A1:A2)",
            "  =1+1",
            "\t=1+1",
        ]

        for sample in samples:
            with self.subTest(sample=sample):
                result = _csv_safe(sample)

                self.assertTrue(result.startswith("'"))

        self.assertEqual(
            _csv_safe("一般社員"),
            "一般社員",
        )

    # ======================================
    # 20. 月次合計は秒単位で集計
    # ======================================

    def test_20_monthly_seconds_aggregated(self):
        # 初日は9時間
        # 追加2日は8時間00分40秒ずつ
        for number in (16, 17):
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

        expected_seconds = 9 * 3600 + 2 * (8 * 3600 + 40)

        self.assertEqual(
            report.total_work_seconds,
            expected_seconds,
        )

        self.assertEqual(
            report.work_display,
            "25時間01分",
        )

    # ======================================
    # 21. 記録なしは欠勤と断定しない
    # ======================================

    def test_21_no_record_is_not_absence(self):
        report = build_monthly_report(
            self.employee,
            date(2026, 9, 1),
        )

        empty_day = next(row for row in report.rows if row.day == date(2026, 9, 14))

        self.assertEqual(
            empty_day.record_key,
            "no_record",
        )

        self.assertIsNone(empty_day.work_seconds)

    # ======================================
    # 22. CSRFトークンがないPOSTを拒否
    # ======================================

    def test_22_csrf_required(self):
        csrf_client = Client(enforce_csrf_checks=True)

        csrf_client.force_login(self.manager)

        response = csrf_client.post(
            reverse(
                "management:month_finalize",
                args=[self.employee.pk, 2026, 9],
            ),
            {"checked_no_record": "on"},
        )

        self.assertEqual(
            response.status_code,
            403,
        )


# ---- management/test_ui_a01.py ----
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


# ---- management/test_ui_a03.py ----
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
        self.url = "/management/employees/"

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


# ---- management/test_ui_a05.py ----
"""A05 操作履歴の表示・権限制御テスト。"""

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from management.templatetags.a05_audit import a05_audit


class A05AuditUiTests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.manager = Employee.objects.create_user(
            employee_number="99601",
            password="A05ManagerTest_2026!",
            is_business_admin=True,
        )

        self.employee = Employee.objects.create_user(
            employee_number="99602",
            password="A05EmployeeTest_2026!",
        )

        self.factory = RequestFactory()
        self.url = "/management/audit/"

    def snapshot(self, user=None, **params):
        request = self.factory.get(
            self.url,
            params,
        )

        request.user = self.manager if user is None else user

        return a05_audit(
            {
                "request": request,
            }
        )

    def test_01_manager_can_open_history(self):
        self.client.force_login(self.manager)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "操作履歴一覧")
        self.assertContains(response, "a05-table-scroll")

    def test_02_regular_employee_cannot_open(self):
        self.client.force_login(self.employee)

        response = self.client.get(self.url)

        self.assertIn(
            response.status_code,
            (302, 403),
        )

    def test_03_regular_employee_has_no_snapshot(self):
        result = self.snapshot(user=self.employee)

        self.assertFalse(result["allowed"])

    def test_04_invalid_date_is_reported(self):
        result = self.snapshot(
            from_date="invalid",
            to_date="2026-11-09",
        )

        self.assertTrue(result["errors"])
        self.assertEqual(result["total_count"], 0)

    def test_05_valid_filter_has_paginator(self):
        result = self.snapshot(
            from_date="2026-11-01",
            to_date="2026-11-09",
        )

        self.assertTrue(result["allowed"])
        self.assertFalse(result["errors"])
        self.assertEqual(
            result["page_obj"].number,
            1,
        )


# ---- management/test_ui_v2.py ----
"""新デザインV2の表示・権限テスト。"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from attendance.models import WorkSession
from corrections.models import CorrectionRequest
from corrections.services import current_values


class ManagementUiV2Tests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.manager = Employee.objects.create_user(
            employee_number="96001",
            password="UiManagerTest_2026!",
            first_name="管理",
            last_name="担当",
            is_business_admin=True,
        )

        self.employee = Employee.objects.create_user(
            employee_number="96002",
            password="UiEmployeeTest_2026!",
            first_name="一般",
            last_name="社員",
        )

        self.day = date(2026, 9, 15)
        self.jst = ZoneInfo("Asia/Tokyo")

        self.session = WorkSession.objects.create(
            employee=self.employee,
            work_date=self.day,
            clock_in_at=self.dt(9),
            clock_out_at=self.dt(18),
            status=WorkSession.Status.COMPLETED,
        )

        self.client.force_login(self.manager)

    def dt(self, hour, minute=0):
        return datetime(
            2026,
            9,
            15,
            hour,
            minute,
            tzinfo=self.jst,
        )

    def create_correction(self, session=None):
        session = session or self.session

        proposal = current_values(session)

        proposal["clock_out_at"] = self.dt(18, 30).isoformat()

        return CorrectionRequest.objects.create(
            work_session=session,
            requested_by=session.employee,
            original_version=session.version,
            proposal=proposal,
            reason="退勤時刻の修正",
            status=CorrectionRequest.Status.PENDING,
        )

    def test_01_monthly_detail_v2_opens(self):
        """新しい月次詳細画面を表示できる。"""

        response = self.client.get(
            reverse(
                "management:employee_month",
                args=[self.employee.pk, 2026, 9],
            )
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "月次詳細・確定",
        )

        self.assertContains(
            response,
            "v2-kpi-grid",
        )

    def test_02_mobile_records_present(self):
        """スマートフォン用の日別カードがある。"""

        response = self.client.get(
            reverse(
                "management:employee_month",
                args=[self.employee.pk, 2026, 9],
            )
        )

        self.assertContains(
            response,
            "v2-mobile-records",
        )

    def test_03_self_month_action_blocked_in_ui(self):
        """自分の月次確定ボタンを表示しない。"""

        response = self.client.get(
            reverse(
                "management:employee_month",
                args=[self.manager.pk, 2026, 9],
            )
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "自分自身の月次勤怠は",
        )

        self.assertNotContains(
            response,
            "この月を確定する",
        )

    def test_04_review_comparison_opens(self):
        """有効値と修正案の比較を表示できる。"""

        correction = self.create_correction()

        response = self.client.get(
            reverse(
                "management:correction_detail",
                args=[correction.pk],
            )
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "現在の有効値",
        )

        self.assertContains(
            response,
            "修正案",
        )

        self.assertContains(
            response,
            "2026/09/15 18:30",
        )

    def test_05_stale_request_ui_blocked(self):
        """勤務データ版が古い申請を審査できない。"""

        correction = self.create_correction()

        self.session.version += 1
        self.session.save(update_fields=["version"])

        response = self.client.get(
            reverse(
                "management:correction_detail",
                args=[correction.pk],
            )
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "申請後に勤務データが変更されています",
        )

        self.assertNotContains(
            response,
            "この申請を承認する",
        )


# ---- management/test_v2_additions.py ----
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from attendance.models import MonthlyClosing
from auditlog.models import AuditLog

from .models import EmploymentInfo


class V2ManagementTests(TestCase):

    def setUp(self):
        Employee = get_user_model()

        self.manager = Employee.objects.create_user(
            employee_number="98001",
            password="V2Manager_2026!",
            first_name="管理",
            last_name="担当",
            is_business_admin=True,
        )

        self.employee_a = Employee.objects.create_user(
            employee_number="98002",
            password="V2EmployeeA_2026!",
            first_name="営業",
            last_name="社員",
        )

        self.employee_b = Employee.objects.create_user(
            employee_number="98003",
            password="V2EmployeeB_2026!",
            first_name="総務",
            last_name="社員",
        )

        EmploymentInfo.objects.create(
            employee=self.employee_a,
            department="営業部",
            hire_date=date(2024, 4, 1),
        )

        EmploymentInfo.objects.create(
            employee=self.employee_b,
            department="総務部",
            hire_date=date(2024, 4, 1),
        )

    def csv_data(self, scope="all", mode="download"):
        return {
            "month": "2026-09",
            "scope": scope,
            "department": "営業部" if scope == "department" else "",
            "employee_number": (
                self.employee_a.employee_number if scope == "employee" else ""
            ),
            "output_format": "monthly",
            "mode": mode,
        }

    def finalize_employee(self, employee):
        MonthlyClosing.objects.create(
            employee=employee,
            target_month=date(2026, 9, 1),
            status=MonthlyClosing.Status.FINALIZED,
            finalized_by=self.manager,
            finalized_at=timezone.now(),
        )

    def test_01_employee_cannot_export(self):
        self.client.force_login(self.employee_a)

        response = self.client.post(
            reverse("management:bulk_export"),
            self.csv_data(),
        )

        self.assertEqual(response.status_code, 403)

    def test_02_unfinalized_all_export_blocked(self):
        self.finalize_employee(self.employee_a)
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("management:bulk_export"),
            self.csv_data(),
        )

        self.assertEqual(response.status_code, 400)

        self.assertFalse(
            AuditLog.objects.filter(action=AuditLog.Action.CSV_EXPORT).exists()
        )

    def test_03_preview_shows_actual_counts(self):
        self.finalize_employee(self.employee_a)
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("management:bulk_export"),
            self.csv_data(mode="preview"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["summary"]["total_count"],
            3,
        )
        self.assertEqual(
            response.context["summary"]["finalized_count"],
            1,
        )

    def test_04_department_export(self):
        self.finalize_employee(self.employee_a)
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("management:bulk_export"),
            self.csv_data(scope="department"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))

        text = response.content.decode("utf-8-sig")

        self.assertIn("98002", text)
        self.assertNotIn("98003", text)

    def test_05_invalid_employment_dates(self):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse(
                "management:employment_edit",
                args=[self.employee_a.pk],
            ),
            {
                "department": "営業部",
                "hire_date": "2026-10-20",
                "leave_date": "2026-10-01",
            },
        )

        self.assertEqual(response.status_code, 200)

        record = EmploymentInfo.objects.get(
            employee=self.employee_a,
        )

        self.assertIsNone(record.leave_date)

    def test_06_employment_edit_audited(self):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse(
                "management:employment_edit",
                args=[self.employee_a.pk],
            ),
            {
                "department": "開発部",
                "hire_date": "2024-04-01",
                "leave_date": "",
            },
        )

        self.assertEqual(response.status_code, 302)

        record = EmploymentInfo.objects.get(
            employee=self.employee_a,
        )

        self.assertEqual(
            record.department,
            "開発部",
        )

        self.assertTrue(
            AuditLog.objects.filter(
                target_model="EmploymentInfo",
                action=AuditLog.Action.EMPLOYEE_UPDATE,
            ).exists()
        )
