# 共通画面・管理機能
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

        response = self.client.get(reverse("management:home"), follow=True)

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

        # 管理者メニューから A01 に移動できる
        self.assertContains(
            response,
            "勤怠一覧",
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
        """スマートフォンではヘッダーの「メニュー」で同じ階層メニューを開ける（21章）。"""

        self.client.force_login(self.manager)

        response = self.client.get(reverse("attendance:home"))

        self.assertContains(
            response,
            'class="app-menu-toggle" aria-controls="app-side"',
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


# 申請・月次管理
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

        detail = self.client.get(reverse(
            "management:employee_month", args=[self.employee.pk, 2026, 9]
        ))
        token = detail.context["closing_form"]["reconciliation_token"].value()

        self.client.post(
            reverse(
                "management:month_finalize",
                args=[self.employee.pk, 2026, 9],
            ),
            {"checked_no_record": "on", "reconciliation_token": token},
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
        self.assertEqual(response.status_code, 302)
        from management.models import ExportBatch
        batch = ExportBatch.objects.latest("pk")
        response = self.client.post(reverse("management:batch_download", args=[batch.output_id, "daily"]))
        self.assertEqual(response.status_code, 200)

        # UTF-8 BOM
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))

        # CRLF
        self.assertIn(
            b"\r\n",
            response.content,
        )

    def test_stale_reconciliation_requires_refresh(self):
        self.client.force_login(self.manager)
        detail = self.client.get(reverse(
            "management:employee_month", args=[self.employee.pk, 2026, 9]
        ))
        token = detail.context["closing_form"]["reconciliation_token"].value()
        self.work.clock_out_at = self.dt(19)
        self.work.version += 1
        self.work.save(update_fields=["clock_out_at", "version"])
        response = self.client.post(reverse(
            "management:month_finalize", args=[self.employee.pk, 2026, 9]
        ), {"checked_no_record": "on", "reconciliation_token": token}, follow=True)
        self.assertContains(response, "再照合")
        self.assertFalse(MonthlyClosing.objects.filter(
            employee=self.employee, target_month=date(2026, 9, 1),
            status=MonthlyClosing.Status.FINALIZED,
        ).exists())

    def test_unfinalized_month_csv_is_blocked(self):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse(
                "management:month_csv",
                args=[self.employee.pk, 2026, 9],
            )
        )

        self.assertEqual(response.status_code, 400)

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


# CSV・監査の回帰試験
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

        self.assertEqual(response.status_code, 400)

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
        self.assertEqual(response.status_code, 302)
        from management.models import ExportBatch
        batch = ExportBatch.objects.latest("pk")
        response = self.client.post(reverse("management:batch_download", args=[batch.output_id, "daily"]))
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
                target_model="ExportBatch",
            ).exists()
        )

    def test_18_csv_header_matches_each_data_row(self):
        finalize_month(**self.closing_kwargs())
        self.client.force_login(self.manager)

        response = self.client.post(self.csv_url())
        from management.models import ExportBatch
        batch = ExportBatch.objects.latest("pk")
        response = self.client.post(reverse("management:batch_download", args=[batch.output_id, "daily"]))
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(rows[0][7], "実働秒数")
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

                self.assertTrue(result.startswith("TXT_"))

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


# A01 勤怠一覧
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

    def test_detail_back_link_restores_search_and_page(self):
        url = reverse("management:employee_month", args=[self.employee.pk, 2026, 11])
        response = self.client.get(url, {
            "back": "month=2026-11&q=99402&department=%E5%96%B6%E6%A5%AD%E9%83%A8&page=2"
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["back_query"],
            "month=2026-11&q=99402&department=%E5%96%B6%E6%A5%AD%E9%83%A8&page=2",
        )
        self.assertEqual(self.client.get(url).context["back_query"], response.context["back_query"])

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


# A03 社員管理
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
            reverse("management:employee_create"),
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
        """一覧から社員詳細へ、社員詳細から所属・在籍日の変更へ進める（画面 16・19）。"""

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        edit_url = reverse(
            "management:employee_edit",
            args=[self.employee.pk],
        )
        self.assertContains(response, edit_url)

        self.assertContains(
            self.client.get(edit_url),
            reverse(
                "management:employment_edit",
                args=[self.employee.pk],
            ),
        )


# A05 操作履歴
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
        for value in ("invalid", "2026-02-31", "2026-13-01"):
            with self.subTest(value=value):
                result = self.snapshot(from_date=value, to_date="2026-11-09")
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


# 管理画面の表示と操作
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

    def test_month_selector_changes_employee_and_month(self):
        url = reverse("management:employee_month", args=[self.employee.pk, 2026, 9])
        response = self.client.get(url, {"employee": self.manager.pk, "month": "2026-10"})
        self.assertRedirects(response, reverse("management:employee_month", args=[self.manager.pk, 2026, 10]))
        self.assertEqual(self.client.get(url, {"employee": "invalid", "month": "2026-10"}).status_code, 404)

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

        # 勤務日と同じ日付の時刻は「HH:MM」だけで比較表に表示する。
        self.assertContains(
            response,
            "18:30",
        )

    def test_invalid_review_preserves_reason_and_field_error(self):
        correction = self.create_correction()
        response = self.client.post(reverse("management:correction_review", args=[correction.pk]), {
            "action": "return", "return_reason": "確認" * 251,
        })
        self.assertTemplateUsed(response, "management/correction_review.html")
        self.assertContains(response, "確認" * 251)
        self.assertTrue(response.context["form"].errors)
        correction.refresh_from_db()
        self.assertEqual(correction.status, CorrectionRequest.Status.PENDING)

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


# 管理機能の追加規則
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
        finalize_month(
            manager_id=self.manager.pk,
            employee_id=employee.pk,
            target_month=date(2026, 9, 1),
            checked_no_record=True,
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

        self.assertEqual(response.status_code, 302)
        from management.models import ExportBatch
        batch = ExportBatch.objects.latest("pk")
        response = self.client.post(reverse("management:batch_download", args=[batch.output_id, "monthly"]))
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

    def test_employment_form_cannot_bypass_department_numbering(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse("management:employment_edit", args=[self.employee_a.pk]), {
            "department": "未登録部署", "hire_date": "2024-04-01", "leave_date": "",
        })
        self.assertContains(response, "部署異動は社員情報の編集画面")
        self.assertEqual(EmploymentInfo.objects.get(employee=self.employee_a).department, "営業部")
        self.employee_a.refresh_from_db()
        self.assertEqual(self.employee_a.employee_number, "98002")
        self.assertFalse(AuditLog.objects.filter(target_model="EmploymentInfo").exists())

    def test_employment_update_rechecks_actor_inside_transaction(self):
        from django.core.exceptions import PermissionDenied
        from .employee_details import employement_edit
        request = RequestFactory().post("/", {"hire_date": "2024-04-01", "leave_date": ""})
        request.user = self.manager
        get_user_model().objects.filter(pk=self.manager.pk).update(is_business_admin=False)
        with self.assertRaises(PermissionDenied):
            employement_edit(request, self.employee_a.pk)
        self.assertFalse(AuditLog.objects.filter(target_model="EmploymentInfo").exists())

    def test_06_employment_edit_audited(self):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse(
                "management:employment_edit",
                args=[self.employee_a.pk],
            ),
            {
                "department": "営業部",
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
            "営業部",
        )

        self.assertTrue(
            AuditLog.objects.filter(
                target_model="EmploymentInfo",
                action=AuditLog.Action.EMPLOYEE_UPDATE,
            ).exists()
        )
        self.employee_a.refresh_from_db()
        self.assertEqual(self.employee_a.hire_date, record.hire_date)

    def test_employee_and_audit_detail_restore_list_filters(self):
        self.client.force_login(self.manager)
        filters = {"q": "98002", "status": "all", "page": "2"}
        self.client.get(reverse("management:employees"), filters)
        response = self.client.get(reverse("management:employment_edit", args=[self.employee_a.pk]))
        self.assertContains(response, '?q=98002&amp;status=all&amp;page=2')
        log = AuditLog.objects.create(actor=self.manager, action=AuditLog.Action.EMPLOYEE_UPDATE, target_model="Employee", target_id=str(self.employee_a.pk))
        self.client.get(reverse("management:audit_history"), {"q": "98002", "action": log.action, "page": "2"})
        response = self.client.get(reverse("management:audit_detail", args=[log.pk]))
        self.assertContains(response, f'?action={log.action}&amp;q=98002&amp;page=2')


# ==========================================
# F11: 管理者のグラフアクセス制御
# ==========================================

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from attendance.templatetags.f11_charts import (
    f11_manager_chart,
)


class F11ManagerChartTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        Employee = get_user_model()

        cls.manager = Employee.objects.create_user(
            employee_number="99101",
            password="TestPassword_2026!",
            is_business_admin=True,
        )

        cls.employee = Employee.objects.create_user(
            employee_number="99102",
            password="TestPassword_2026!",
        )

    def make_request(self, user):
        factory = RequestFactory()

        request = factory.get("/management/employees/1/months/2026/11/")

        request.user = user

        request.resolver_match = SimpleNamespace(
            view_name="management:employee_month",
            kwargs={
                "employee_id": self.employee.pk,
                "year": 2026,
                "month": 11,
            },
        )

        return request

    def test_regular_employee_is_denied(self):
        """一般社員には管理者向けデータを返さない。"""

        request = self.make_request(self.employee)

        result = f11_manager_chart({"request": request})

        self.assertIsNone(result)

    @patch("attendance.templatetags.f11_charts.build_work_hours_chart")
    def test_manager_can_request_chart(self, mock_build):
        """管理者は対象社員のグラフを取得できる。"""

        mock_build.return_value = {
            "kind": "work_hours",
            "rows": [],
        }

        request = self.make_request(self.manager)

        result = f11_manager_chart({"request": request})

        self.assertIsNotNone(result)

        mock_build.assert_called_once()

        self.assertEqual(
            mock_build.call_args.args[0].pk,
            self.employee.pk,
        )

    def test_inactive_manager_is_denied(self):
        """無効化された管理者にはデータを返さない。"""

        self.manager.is_active = False

        request = self.make_request(self.manager)

        result = f11_manager_chart({"request": request})

        self.assertIsNone(result)


# v1.4.3 確定版・代理申請の回帰試験

"""Frozen closing and paired CSV export acceptance checks."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import RequestFactory, TestCase
from django.urls import resolve, reverse

from attendance.models import WorkSession
from attendance.templatetags.f11_charts import f11_manager_chart
from management.export_batches import create_export_batch, current_snapshots, write_snapshot_csv
from management.services import finalize_month, reopen_month
from corrections.models import CorrectionRequest


class FrozenExportTests(TestCase):
    def setUp(self):
        Employee = get_user_model()
        self.employee = Employee.objects.create_user(
            employee_number="0007", password="TestPassword_2026!",
            hire_date=date(2024, 1, 1), first_name="=営業",
        )
        self.manager = Employee.objects.create_user(
            employee_number="9001", password="TestPassword_2026!",
            is_business_admin=True,
        )
        WorkSession.objects.create(
            employee=self.employee, work_date=date(2024, 1, 2),
            clock_in_at=datetime(2024, 1, 2, 9, tzinfo=ZoneInfo("Asia/Tokyo")),
            clock_out_at=datetime(2024, 1, 2, 18, tzinfo=ZoneInfo("Asia/Tokyo")),
            status=WorkSession.Status.COMPLETED,
        )

    def test_reopen_invalidates_both_files_of_output_id(self):
        closing = finalize_month(
            manager_id=self.manager.pk, employee_id=self.employee.pk,
            target_month=date(2024, 1, 1), checked_no_record=True,
        )
        self.assertEqual(closing.snapshot["employee_number"], "0007")
        batch = create_export_batch(self.manager, [self.employee], date(2024, 1, 1))
        daily = write_snapshot_csv(current_snapshots(batch), "daily")
        monthly = write_snapshot_csv(current_snapshots(batch), "monthly")
        self.assertIn("TXT_=営業", daily)
        self.assertIn("0007", monthly)
        self.assertIn("32400", monthly)
        reopen_month(
            manager_id=self.manager.pk, employee_id=self.employee.pk,
            target_month=date(2024, 1, 1), reason="訂正のため",
        )
        with self.assertRaises(ValueError):
            current_snapshots(batch)

    def test_finalized_manager_chart_uses_frozen_values(self):
        closing = finalize_month(
            manager_id=self.manager.pk, employee_id=self.employee.pk,
            target_month=date(2024, 1, 1), checked_no_record=True,
        )
        self.assertEqual(closing.integrity_check_result["issue_count"], 0)
        url = reverse("management:employee_month", args=[self.employee.pk, 2024, 1])
        request = RequestFactory().get(url)
        request.user = self.manager
        request.resolver_match = resolve(url)
        original = f11_manager_chart({"request": request})
        self.assertEqual(original["rows"][1]["seconds"], 32400)
        WorkSession.objects.filter(employee=self.employee).update(
            clock_out_at=datetime(2024, 1, 2, 20, tzinfo=ZoneInfo("Asia/Tokyo")),
        )
        frozen = f11_manager_chart({"request": request})
        self.assertEqual(frozen["rows"][1]["seconds"], 32400)


class ProxyConfirmationTests(TestCase):
    def setUp(self):
        Employee = get_user_model()
        self.employee = Employee.objects.create_user(
            employee_number="0021", password="TestPassword_2026!",
            hire_date=date(2024, 1, 1), is_active=False,
        )
        self.manager = Employee.objects.create_user(
            employee_number="9021", password="TestPassword_2026!",
            is_business_admin=True,
        )
        self.client.force_login(self.manager)
        self.url = reverse("management:proxy_correction", args=[self.employee.pk, 2024, 1, 2])

    def test_confirmation_return_preserves_input_and_submission(self):
        response = self.client.post(self.url, {
            "clock_in_at": "2024-01-02T09:00:00",
            "clock_out_at": "2024-01-02T18:00:00",
            "reason": "本人から電話で申告", "proxy_reason": "アカウント停止中",
            "evidence": "勤務表を確認", "breaks-TOTAL_FORMS": "0",
            "breaks-INITIAL_FORMS": "0", "breaks-MIN_NUM_FORMS": "0",
            "breaks-MAX_NUM_FORMS": "20",
        })
        self.assertEqual(response.status_code, 200)
        token = response.context["confirm_token"]
        self.assertContains(response, "代理申請の確認")
        returned = self.client.post(self.url, {"return_token": token})
        self.assertEqual(returned.status_code, 200)
        self.assertEqual(returned.context["form"].initial["reason"], "本人から電話で申告")
        self.assertEqual(returned.context["evidence_form"].initial["evidence"], "勤務表を確認")
        self.assertEqual(CorrectionRequest.objects.count(), 0)
        confirmed = self.client.post(self.url, {"confirm_token": token})
        self.assertEqual(confirmed.status_code, 302)
        correction = CorrectionRequest.objects.get()
        self.assertTrue(correction.is_proxy)
        self.assertIsNone(correction.work_session_id)

    def test_malformed_signed_token_does_not_crash(self):
        token = signing.dumps({"actor_id": self.manager.pk}, salt="attendance-proxy-v1")
        response = self.client.post(self.url, {"return_token": token})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "最初から入力してください")
        self.assertEqual(CorrectionRequest.objects.count(), 0)


# 管理者権限

"""業務管理者権限の画面と人数制約。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from auditlog.models import AuditLog
from management.models import Department
from management.templatetags.a03_directory import a03_directory


class BusinessAdminRoleTests(TestCase):
    """業務管理者権限の操作・人数制約に関するテスト。"""

    def setUp(self):
        Employee = get_user_model()

        self.manager = Employee.objects.create_user(
            employee_number="91001",
            password="TestPassword_2026!",
            is_business_admin=True,
        )

        self.employee = Employee.objects.create_user(
            employee_number="91002",
            password="TestPassword_2026!",
        )

        self.other = Employee.objects.create_user(
            employee_number="91003",
            password="TestPassword_2026!",
        )

        self.client.force_login(self.manager)

    def url(self, employee=None):
        return reverse(
            "management:employee_role",
            args=[(employee or self.employee).pk],
        )

    def data(
        self,
        expected="employee",
        desired="admin",
        reason="運用担当の承認済み",
    ):
        return {
            "expected_role": expected,
            "desired_role": desired,
            "change_reason": reason,
        }

    def test_role_list_search_keeps_global_manager_count(self):
        self.other.is_business_admin = True
        self.other.save(update_fields=["is_business_admin"])
        response = self.client.get(reverse("management:role_list"), {"q": self.employee.employee_number, "role": "employee"})
        self.assertEqual([item.pk for item in response.context["employees"]], [self.employee.pk])
        self.assertEqual(response.context["active_manager_count"], 2)
        self.assertContains(response, self.url())
        detail = self.client.get(self.url())
        self.assertContains(detail, '?q=91002&amp;role=employee')

    def test_sole_manager_can_grant_second_manager_with_audit(self):
        # 社員一覧 → 社員詳細 → 業務管理者権限の変更（画面 16・19）
        directory = self.client.get(reverse("management:employees"))
        detail_url = reverse("management:employee_edit", args=[self.employee.pk])
        self.assertContains(directory, detail_url)
        self.assertContains(self.client.get(detail_url), self.url())

        edit = self.client.get(
            reverse(
                "management:employee_edit",
                args=[self.employee.pk],
            )
        )
        self.assertContains(edit, self.url())

        self.assertContains(
            self.client.get(self.url()),
            "業務管理者権限の変更",
        )

        response = self.client.post(
            self.url(),
            self.data(),
        )
        self.assertEqual(response.status_code, 302)

        self.employee.refresh_from_db()
        self.assertTrue(self.employee.is_business_admin)
        self.assertFalse(self.employee.is_staff)
        self.assertFalse(self.employee.is_superuser)

        role_logs = AuditLog.objects.filter(
            action=AuditLog.Action.ROLE_CHANGE,
            target_employee=self.employee,
        )
        self.assertEqual(role_logs.count(), 1)

        log = role_logs.get()
        self.assertEqual(log.actor_id, self.manager.pk)
        self.assertEqual(log.reason, "運用担当の承認済み")
        self.assertEqual(
            log.before_data["is_business_admin"],
            False,
        )
        self.assertEqual(
            log.after_data["is_business_admin"],
            True,
        )

        self.client.force_login(self.employee)
        self.assertRedirects(
            self.client.get(reverse("management:home")),
            reverse("management:attendance_list"),
        )

    def test_cannot_revoke_one_of_only_two_active_managers(self):
        self.client.post(
            self.url(),
            self.data(),
        )

        response = self.client.post(
            self.url(),
            self.data(
                expected="admin",
                desired="employee",
                reason="管理者交代",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2人以上")

        self.employee.refresh_from_db()
        self.assertTrue(self.employee.is_business_admin)

        self.assertEqual(
            AuditLog.objects.filter(
                action=AuditLog.Action.ROLE_CHANGE,
                target_employee=self.employee,
            ).count(),
            1,
        )

    def test_third_manager_can_be_revoked_but_not_self(self):
        self.client.post(
            self.url(),
            self.data(),
        )

        self.other.is_business_admin = True
        self.other.save(update_fields=["is_business_admin"])

        response = self.client.post(
            self.url(),
            self.data(
                expected="admin",
                desired="employee",
                reason="交代済み",
            ),
        )

        self.assertEqual(response.status_code, 302)

        self.employee.refresh_from_db()
        self.assertFalse(self.employee.is_business_admin)

        self.assertEqual(
            get_user_model()
            .objects.filter(
                is_active=True,
                is_business_admin=True,
            )
            .count(),
            2,
        )

        self.client.force_login(self.employee)
        self.assertEqual(
            self.client.get(reverse("management:home")).status_code,
            403,
        )

        self.client.force_login(self.manager)

        own = self.client.post(
            self.url(self.manager),
            self.data(
                expected="admin",
                desired="employee",
                reason="自分を取消",
            ),
        )

        self.assertContains(
            own,
            "自分自身の業務管理者権限",
        )

        self.manager.refresh_from_db()
        self.assertTrue(self.manager.is_business_admin)

    def test_inactive_and_technical_accounts_cannot_be_granted(self):
        self.employee.is_active = False
        self.employee.save(update_fields=["is_active"])

        self.assertContains(
            self.client.post(
                self.url(),
                self.data(),
            ),
            "利用停止中",
        )

        self.employee.refresh_from_db()
        self.assertFalse(self.employee.is_business_admin)

        self.other.is_staff = True
        self.other.save(update_fields=["is_staff"])

        self.assertContains(
            self.client.post(
                self.url(self.other),
                self.data(),
            ),
            "技術管理用",
        )

        self.other.refresh_from_db()
        self.assertFalse(self.other.is_business_admin)

    def test_stale_form_and_missing_reason_are_rejected(self):
        self.assertContains(
            self.client.post(
                self.url(),
                self.data(reason=""),
            ),
            "変更理由",
        )

        self.employee.is_business_admin = True
        self.employee.save(update_fields=["is_business_admin"])

        response = self.client.post(
            self.url(),
            self.data(),
        )

        self.assertContains(
            response,
            "再読み込み",
        )

    def test_ordinary_employee_is_forbidden_and_csrf_is_required(self):
        self.client.force_login(self.other)

        self.assertEqual(
            self.client.get(self.url()).status_code,
            403,
        )

        self.assertEqual(
            self.client.post(
                self.url(),
                self.data(),
            ).status_code,
            403,
        )

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.manager)

        self.assertEqual(
            client.post(
                self.url(),
                self.data(),
            ).status_code,
            403,
        )

    def test_audit_failure_rolls_back_role_grant(self):
        with patch(
            "accounts.signals.AuditLog.objects.create",
            side_effect=RuntimeError("audit failed"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    self.url(),
                    self.data(),
                )

        self.employee.refresh_from_db()
        self.assertFalse(self.employee.is_business_admin)

    def test_directory_manager_count_excludes_inactive_accounts(self):
        self.other.is_business_admin = True
        self.other.is_active = False

        self.other.save(
            update_fields=[
                "is_business_admin",
                "is_active",
            ]
        )

        request = RequestFactory().get(reverse("management:employees"))
        request.user = self.manager

        self.assertEqual(
            a03_directory({"request": request})["manager_count"],
            1,
        )

    def test_employee_edit_still_works_and_cannot_disable_second_manager(self):
        """社員編集と管理者2人以上の保護を検証する。"""

        # Phase 2対応：
        # テスト用DBに部署マスターを作成する。
        department = Department.objects.create(
            name="総務",
            code=1,
            is_active=True,
        )

        edit_url = reverse(
            "management:employee_edit",
            args=[self.employee.pk],
        )
        edit_state = self.client.get(edit_url).context["edit_state"]

        # 1. 一般社員の情報更新
        updated = self.client.post(
            edit_url,
            {
                "employee_number": self.employee.employee_number,
                "first_name": "更新",
                "last_name": "社員",
                "department_choice": str(department.pk),
                "is_active": "on",
                "change_reason": "社員情報の更新",
                "edit_state": edit_state,
            },
        )

        # 失敗時にフォームエラーを確認できるようにする。
        if updated.status_code != 302:
            form = updated.context.get("form") if updated.context else None
            errors = (
                form.errors.as_json()
                if form is not None
                else "フォームエラーを取得できませんでした。"
            )
            self.fail(
                "社員情報の更新に失敗しました。"
                f" HTTPステータス: {updated.status_code}"
                f" フォームエラー: {errors}"
            )

        self.assertEqual(updated.status_code, 302)

        self.employee.refresh_from_db()
        self.assertEqual(self.employee.first_name, "更新")
        self.assertEqual(self.employee.department, "総務")

        # 2. 2人目の管理者に昇格
        role_response = self.client.post(
            self.url(),
            self.data(),
        )

        self.assertEqual(role_response.status_code, 302)

        self.employee.refresh_from_db()
        self.assertTrue(self.employee.is_business_admin)

        # 3. 管理者が2人しかいない状態で
        #    2人目を利用停止にしようとする。
        disabled = self.client.post(
            edit_url,
            {
                "employee_number": self.employee.employee_number,
                "first_name": "更新",
                "last_name": "社員",
                "department_choice": str(department.pk),
                "change_reason": "管理者交代前の停止試行",
                "edit_state": self.client.get(edit_url).context["edit_state"],
            },
        )

        # 管理者2人以上の制約により停止できない。
        self.assertContains(
            disabled,
            "2人以上",
        )

        self.employee.refresh_from_db()
        self.assertTrue(self.employee.is_active)


# 部署登録・社員番号

"""部署登録・部署別自動採番・部署コード再利用防止の受入テスト。"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
import uuid
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.db import IntegrityError, OperationalError, transaction
from django.test import TestCase
from django.core.management import call_command
from django.urls import reverse

from management.department_rules import (
    available_department_codes,
    normalize_department_name,
    used_department_codes,
)
from management.numbering import next_employee_number
from auditlog.models import AuditLog
from management.models import (
    Department,
    DepartmentRegistration,
    EmployeeNumberHistory,
    EmploymentInfo,
    EmployeeNumberOperation,
)


class DepartmentRulesTests(TestCase):
    def test_normalize_department_name(self):
        self.assertEqual(normalize_department_name("  営業部  "), "営業部")
        with self.assertRaises(ValidationError):
            normalize_department_name("  ")
        with self.assertRaises(ValidationError):
            normalize_department_name("あ" * 101)

    def test_new_department_code_is_available_without_employees(self):
        Department.objects.create(name="ITソリューション部", code=3)
        self.assertIn(3, used_department_codes())
        self.assertNotIn(3, available_department_codes())
        self.assertEqual(Department.objects.filter(code=3).count(), 1)

    def test_inactive_department_code_is_not_reusable(self):
        Department.objects.create(name="旧営業部", code=4, is_active=False)
        self.assertNotIn(4, available_department_codes())

    def test_existing_employee_number_reserves_its_prefix(self):
        Employee = get_user_model()
        Employee.objects.create_user(employee_number="50001", password="TestPassword_2026!")
        self.assertNotIn(5, available_department_codes())

    def test_legacy_number_reserves_unregistered_code_but_existing_department_can_issue(self):
        Employee = get_user_model()
        Employee.objects.create_user(employee_number="30001", password="TestPassword_2026!")
        department = Department.objects.create(name="既存部署", code=1)
        self.assertNotIn(3, available_department_codes())
        self.assertEqual(next_employee_number(department), "10001")

    def test_code_exhaustion_stops_only_new_departments(self):
        Employee = get_user_model()
        for code in range(2, 10):
            Employee.objects.create_user(
                employee_number=f"{code}0001", password="TestPassword_2026!",
            )
        department = Department.objects.create(name="既存部署", code=1)
        self.assertEqual(available_department_codes(), [])
        self.assertEqual(next_employee_number(department), "10001")

    def test_number_history_reserves_its_prefix(self):
        Employee = get_user_model()
        employee = Employee.objects.create_user(
            employee_number="91001", password="TestPassword_2026!"
        )
        department = Department.objects.create(name="旧開発部", code=6, is_active=False)
        EmployeeNumberHistory.objects.create(
            employee=employee, department=department, employee_number="60001"
        )
        self.assertNotIn(6, available_department_codes())

    def test_department_code_must_be_between_one_and_nine(self):
        for code in (0, 10):
            with self.subTest(code=code):
                department = Department(name=f"範囲外{code}", code=code)
                with self.assertRaises(ValidationError):
                    department.full_clean()

    def test_duplicate_department_code_is_rejected(self):
        Department.objects.create(name="営業部", code=1)
        with self.assertRaises(ValidationError):
            Department(name="総務部", code=1).full_clean()

    def test_database_rejects_duplicate_department_code(self):
        Department.objects.create(name="営業部", code=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Department.objects.create(name="総務部", code=1)


class LegacyNumberingMigrationTests(TestCase):
    def test_migration_preserves_old_numbers_and_is_repeatable(self):
        Employee = get_user_model()
        manager = Employee.objects.create_user(
            employee_number="90001", password="TestPassword_2026!",
            department="営業部", is_business_admin=True,
        )
        old = Employee.objects.create_user(
            employee_number="00999", password="TestPassword_2026!",
            department="開発部", is_active=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.json"
            path.write_text(json.dumps({"開発部": 1, "営業部": 2}), encoding="utf-8")
            options = {"mapping_file": str(path), "actor_number": manager.employee_number}
            call_command("migrate_legacy_numbering", dry_run=True, **options)
            self.assertFalse(Department.objects.exists())
            call_command("migrate_legacy_numbering", **options)
            call_command("migrate_legacy_numbering", **options)
        self.assertEqual(Department.objects.count(), 2)
        self.assertEqual(DepartmentRegistration.objects.count(), 2)
        self.assertEqual(EmployeeNumberHistory.objects.count(), 2)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.DEPARTMENT_CREATE).count(), 2)
        self.assertEqual(EmployeeNumberHistory.objects.get(employee=old).department.code, 1)
        self.assertNotIn(9, available_department_codes())
        self.assertEqual(next_employee_number(Department.objects.get(code=2)), "20001")


class EmployeeDepartmentSelectionTests(TestCase):
    def setUp(self):
        Employee = get_user_model()
        self.manager = Employee.objects.create_user(
            employee_number="91001", password="TestPassword_2026!", is_business_admin=True
        )
        self.employee = Employee.objects.create_user(
            employee_number="91002", password="TestPassword_2026!"
        )
        self.department = Department.objects.create(
            name="ITソリューション部", code=3, is_active=True
        )
        self.client.force_login(self.manager)

    def test_employee_confirmation_back_preserves_input_without_creation(self):
        data = {"first_name": "太郎", "last_name": "佐藤", "department_choice": str(self.department.pk),
                "hire_date": "2026-04-01", "operation_id": str(uuid.uuid4())}
        url = reverse("management:employee_create")
        self.assertTemplateUsed(self.client.post(url, {**data, "preview": "1"}), "management/employee_confirm.html")
        response = self.client.post(url, {**data, "back": "1"})
        self.assertTemplateUsed(response, "management/employee_form.html")
        self.assertEqual(response.context["form"]["first_name"].value(), "太郎")
        self.assertEqual(response.context["operation_id"], data["operation_id"])
        self.assertFalse(EmployeeNumberOperation.objects.exists())
        self.assertFalse(EmployeeNumberHistory.objects.exists())

    def test_zero_employee_department_is_available_on_create_form(self):
        response = self.client.get(reverse("management:employee_create"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("department_choice", response.context["form"].fields)
        field = response.context["form"].fields["department_choice"]
        self.assertTrue(field.queryset.filter(pk=self.department.pk).exists())

    def test_employee_preview_does_not_issue_number_until_confirmed(self):
        data = {
            "first_name": "太郎", "last_name": "佐藤",
            "department_choice": str(self.department.pk),
            "hire_date": "2026-04-01", "operation_id": str(uuid.uuid4()),
        }
        response = self.client.post(reverse("management:employee_create"), {
            **data, "preview": "1",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "社員登録内容の確認")
        self.assertContains(response, "30001")
        self.assertFalse(EmployeeNumberHistory.objects.exists())
        response = self.client.post(reverse("management:employee_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EmployeeNumberHistory.objects.get().employee_number, "30001")

    def test_employee_creation_saves_selected_department(self):
        response = self.client.post(
            reverse("management:employee_create"),
            {
                "first_name": "太郎",
                "last_name": "佐藤",
                "department_choice": str(self.department.pk),
                "hire_date": "2026-04-01",
            },
        )
        self.assertEqual(response.status_code, 200)
        Employee = get_user_model()
        created = Employee.objects.filter(employee_number="30001").first()
        self.assertIsNotNone(created, getattr(response.context.get("form"), "errors", None) if response.context else None)
        self.assertEqual(created.department, "ITソリューション部")
        self.assertEqual(EmploymentInfo.objects.get(employee=created).department, "ITソリューション部")
        self.assertTrue(EmployeeNumberHistory.objects.filter(
            employee=created, department=self.department, employee_number="30001"
        ).exists())

    def test_create_replay_does_not_issue_second_number_or_password(self):
        data = {
            "first_name": "太郎", "last_name": "佐藤",
            "department_choice": str(self.department.pk),
            "hire_date": "2026-04-01", "operation_id": str(uuid.uuid4()),
        }
        url = reverse("management:employee_create")
        first = self.client.post(url, data)
        self.assertEqual(first.status_code, 200)
        replay = self.client.post(url, data)
        self.assertEqual(replay.status_code, 302)
        self.assertEqual(EmployeeNumberHistory.objects.filter(department=self.department).count(), 1)
        self.assertEqual(EmployeeNumberOperation.objects.filter(kind="create").count(), 1)
        different = self.client.post(url, {**data, "first_name": "次郎"})
        self.assertEqual(different.status_code, 409)

    def test_candidate_follows_max_history_and_rejects_manual_number(self):
        Employee = get_user_model()
        old = Employee.objects.create_user(employee_number="30007", password="TestPassword_2026!")
        EmployeeNumberHistory.objects.create(
            employee=old, department=self.department, employee_number="30007"
        )
        old.employee_number = "91007"
        old.save(update_fields=["employee_number"])
        self.assertEqual(next_employee_number(self.department), "30008")
        response = self.client.post(reverse("management:employee_create"), {
            "employee_number": "39999", "first_name": "花子", "last_name": "山田",
            "department_choice": str(self.department.pk), "hire_date": "2026-04-01",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Employee.objects.filter(employee_number="30008").exists())
        self.assertFalse(Employee.objects.filter(employee_number="39999").exists())

    def test_department_transfer_keeps_old_number_in_history(self):
        url = reverse("management:employee_edit", args=[self.employee.pk])
        state = self.client.get(url).context["edit_state"]
        response = self.client.post(
            url,
            {
                "first_name": "更新", "last_name": "社員",
                "department_choice": str(self.department.pk),
                "is_active": "on", "change_reason": "部署異動",
                "edit_state": state,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.employee_number, "30001")
        self.assertTrue(EmployeeNumberHistory.objects.filter(employee_number="91002").exists())
        self.assertTrue(EmployeeNumberHistory.objects.filter(employee_number="30001").exists())
        self.client.logout()
        login_url = reverse("accounts:login")
        old_login = self.client.post(login_url, {
            "username": "91002", "password": "TestPassword_2026!"
        })
        self.assertEqual(old_login.status_code, 200)
        new_login = self.client.post(login_url, {
            "username": "30001", "password": "TestPassword_2026!"
        })
        self.assertEqual(new_login.status_code, 302)

    def test_candidate_api_and_number_limit(self):
        candidate_url = reverse("management:employee_number_candidate")
        response = self.client.get(candidate_url, {"department": self.department.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["number"], "30001")
        EmployeeNumberHistory.objects.create(
            employee=self.employee, department=self.department, employee_number="39999"
        )
        response = self.client.get(candidate_url, {"department": self.department.pk})
        self.assertEqual(response.status_code, 400)
        self.assertIn("上限", response.json()["error"])
        create = self.client.post(reverse("management:employee_create"), {
            "first_name": "花子", "last_name": "山田",
            "department_choice": str(self.department.pk), "hire_date": "2026-04-01",
        })
        self.assertContains(create, "上限")
        self.assertFalse(get_user_model().objects.filter(employee_number__startswith="3").exists())

    def test_inactive_department_cannot_be_selected_for_new_employee(self):
        self.department.is_active = False
        self.department.save(update_fields=["is_active"])
        response = self.client.post(
            reverse("management:employee_create"),
            {
                "first_name": "太郎",
                "last_name": "佐藤",
                "department_choice": str(self.department.pk),
                "hire_date": "2026-04-01",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(employee_number="30001").exists())
        self.assertTrue(response.context["form"].errors)

    def test_ordinary_employee_cannot_create_employee(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse("management:employee_create"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get(reverse("management:employee_number_candidate")).status_code, 403)
        self.assertEqual(self.client.get(reverse("management:role_list")).status_code, 403)

    def test_employee_edit_updates_department_and_employment_info(self):
        url = reverse("management:employee_edit", args=[self.employee.pk])
        state = self.client.get(url).context["edit_state"]
        response = self.client.post(
            url,
            {
                "employee_number": self.employee.employee_number,
                "first_name": "更新",
                "last_name": "社員",
                "department_choice": str(self.department.pk),
                "is_active": "on",
                "change_reason": "所属部署の変更",
                "edit_state": state,
            },
        )
        self.assertEqual(response.status_code, 302, getattr(response.context.get("form"), "errors", None) if response.context else None)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.department, "ITソリューション部")
        self.assertEqual(EmploymentInfo.objects.get(employee=self.employee).department, "ITソリューション部")

    def test_stale_employee_edit_is_rejected(self):
        url = reverse("management:employee_edit", args=[self.employee.pk])
        state = self.client.get(url).context["edit_state"]
        get_user_model().objects.filter(pk=self.employee.pk).update(first_name="別の更新")
        response = self.client.post(url, {
            "first_name": "古い入力", "last_name": "社員",
            "department_choice": str(self.department.pk),
            "is_active": "on", "change_reason": "部署異動",
            "edit_state": state,
        })
        self.assertContains(response, "別の操作で変更", status_code=200)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.first_name, "別の更新")
        self.assertEqual(self.employee.employee_number, "91002")


class DepartmentManagementAcceptanceTests(TestCase):
    def setUp(self):
        Employee = get_user_model()
        self.manager = Employee.objects.create_user(
            employee_number="91011", password="TestPassword_2026!", is_business_admin=True
        )
        self.employee = Employee.objects.create_user(
            employee_number="91012", password="TestPassword_2026!"
        )
        self.client.force_login(self.manager)
        self.create_url = reverse("management:department_create")

    def create_data(self, operation_id=None, **changes):
        data = {
            "name": "営業部",
            "code": "1",
            "is_active": "on",
            "operation_id": str(operation_id or uuid.uuid4()),
        }
        data.update(changes)
        return data

    def test_department_confirmation_back_preserves_input_without_creation(self):
        data = self.create_data(name="営業部")
        self.assertTemplateUsed(self.client.post(self.create_url, {**data, "preview": "1"}), "management/departments/confirm.html")
        response = self.client.post(self.create_url, {**data, "back": "1"})
        self.assertTemplateUsed(response, "management/departments/form.html")
        self.assertEqual(response.context["form"]["name"].value(), "営業部")
        self.assertEqual(response.context["operation_id"], data["operation_id"])
        self.assertFalse(Department.objects.exists())
        self.assertFalse(DepartmentRegistration.objects.exists())

    def test_department_preview_does_not_register_until_confirmed(self):
        data = self.create_data()
        response = self.client.post(self.create_url, {**data, "preview": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "部署登録内容の確認")
        self.assertFalse(Department.objects.exists())
        response = self.client.post(self.create_url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Department.objects.get().name, "営業部")

    def test_create_writes_one_audit_and_replay_does_not_duplicate_it(self):
        data = self.create_data(name="  営業部  ")
        first_response = self.client.post(self.create_url, data)
        self.assertEqual(first_response.status_code, 302)
        department = Department.objects.get(code=1)
        self.assertEqual(first_response.url, reverse(
            "management:department_registration_result",
            args=[data["operation_id"]],
        ))
        result = self.client.get(first_response.url)
        self.assertContains(result, f"<dd>{department.pk}</dd>", html=True)
        self.assertContains(result, "営業部")
        registration = DepartmentRegistration.objects.get(department=department)
        self.assertEqual(registration.name, "営業部")
        self.assertTrue(registration.is_active)
        audit = AuditLog.objects.get(action=AuditLog.Action.DEPARTMENT_CREATE)
        self.assertEqual(audit.actor, self.manager)
        self.assertEqual(audit.target_id, str(department.pk))
        self.assertEqual(audit.before_data, {})
        self.assertEqual(
            audit.after_data, {"name": "営業部", "code": 1, "is_active": True}
        )
        self.assertEqual(audit.details["operation_id"], data["operation_id"])

        replay = self.client.post(self.create_url, data)
        self.assertEqual(replay.status_code, 302)
        self.assertEqual(replay.url, first_response.url)
        self.assertEqual(Department.objects.count(), 1)
        self.assertEqual(DepartmentRegistration.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.DEPARTMENT_CREATE).count(), 1)

    def test_reused_operation_with_changed_name_code_or_status_is_rejected(self):
        data = self.create_data()
        self.assertEqual(self.client.post(self.create_url, data).status_code, 302)
        for changes in ({"name": "総務部"}, {"code": "2"}, {"is_active": ""}):
            with self.subTest(changes=changes):
                response = self.client.post(self.create_url, {**data, **changes})
                self.assertEqual(response.status_code, 409)
                self.assertContains(response, "同じ操作IDで異なる内容", status_code=409)
        self.assertEqual(Department.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.DEPARTMENT_CREATE).count(), 1)

    def test_legacy_operation_without_status_snapshot_is_rejected(self):
        data = self.create_data()
        department = Department.objects.create(name=data["name"], code=1)
        DepartmentRegistration.objects.create(
            department=department,
            actor=self.manager,
            operation_id=uuid.UUID(data["operation_id"]),
            name=department.name,
            code=department.code,
        )
        response = self.client.post(self.create_url, data)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Department.objects.count(), 1)
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.DEPARTMENT_CREATE).exists())

    def test_edit_audits_changes_and_rejects_submitted_code_change(self):
        department = Department.objects.create(name="営業部", code=1)
        url = reverse("management:department_edit", args=[department.pk])
        response = self.client.post(url, {"name": "総務部", "is_active": ""})
        self.assertEqual(response.status_code, 302)
        department.refresh_from_db()
        self.assertEqual((department.name, department.code, department.is_active), ("総務部", 1, False))
        audit = AuditLog.objects.get(action=AuditLog.Action.DEPARTMENT_UPDATE)
        self.assertEqual(audit.actor, self.manager)
        self.assertEqual(audit.target_id, str(department.pk))
        self.assertEqual(audit.before_data, {"name": "営業部", "code": 1, "is_active": True})
        self.assertEqual(audit.after_data, {"name": "総務部", "code": 1, "is_active": False})

        response = self.client.post(url, {"name": "改ざん", "code": "2", "is_active": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "部署コードは変更できません")
        department.refresh_from_db()
        self.assertEqual((department.name, department.code), ("総務部", 1))
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.DEPARTMENT_UPDATE).count(), 1)

    def test_department_name_cannot_change_while_employees_use_it(self):
        department = Department.objects.create(name="営業部", code=1)
        get_user_model().objects.filter(pk=self.employee.pk).update(department=department.name)
        response = self.client.post(
            reverse("management:department_edit", args=[department.pk]),
            {"name": "新営業部", "is_active": "on"},
        )
        self.assertContains(response, "所属社員がいる部署名は変更できません")
        department.refresh_from_db()
        self.assertEqual(department.name, "営業部")

    def test_stale_code_choice_and_database_lock_do_not_leave_partial_registration(self):
        data = self.create_data()
        with patch("management.department_views.available_department_codes", return_value=[]):
            response = self.client.post(self.create_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "この部署コードは既に使用されています")
        self.assertFalse(Department.objects.exists())

        with patch("management.department_views.DepartmentForm.save", side_effect=OperationalError("database is locked")):
            response = self.client.post(self.create_url, data)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "登録が競合しました", status_code=409)
        self.assertFalse(Department.objects.exists())
        self.assertFalse(DepartmentRegistration.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.DEPARTMENT_CREATE).exists())

    def test_audit_failure_rolls_back_registration(self):
        with patch("management.department_views.AuditLog.objects.create", side_effect=IntegrityError("audit failed")):
            response = self.client.post(self.create_url, self.create_data())
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Department.objects.exists())
        self.assertFalse(DepartmentRegistration.objects.exists())

    def test_ordinary_employee_cannot_manage_departments(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(self.create_url).status_code, 403)
        self.assertEqual(self.client.post(self.create_url, self.create_data()).status_code, 403)
        self.assertFalse(Department.objects.exists())


# DB外の番号保全記録

"""番号保全記録とバックアップ復元の停止条件。"""

import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse

from auditlog.models import AuditLog
from management.models import Department, DepartmentRegistration, EmployeeNumberHistory
from management.numbering_ledger import (
    NumberingLedgerError, cancel_pending, export_snapshot, read_snapshot, reconcile_pending,
    require_numbering_ready, reserve_pending, restore_departments, verify_snapshot,
)


class NumberingLedgerTests(TestCase):
    def setUp(self):
        Employee = get_user_model()
        self.manager = Employee.objects.create_user(
            employee_number="90001", password="TestPassword_2026!", is_business_admin=True,
        )
        self.department = Department.objects.create(name="新部署", code=3)
        self.operation_id = uuid.uuid4()
        self.registration = DepartmentRegistration.objects.create(
            department=self.department, actor=self.manager, operation_id=self.operation_id,
            name=self.department.name, code=self.department.code, is_active=True,
        )
        self.audit = AuditLog.objects.create(
            actor=self.manager, action=AuditLog.Action.DEPARTMENT_CREATE,
            target_model=Department._meta.label, target_id=str(self.department.pk),
            before_data={}, after_data={"name": "新部署", "code": 3, "is_active": True},
            details={"operation_id": str(self.operation_id)},
        )
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "numbering-ledger.json"
        export_snapshot(self.path)

    def test_tampered_or_missing_ledger_stops_issuance(self):
        with override_settings(NUMBERING_LEDGER_PATH=self.path), patch(
            "management.numbering_ledger._test_database", return_value=False
        ):
            require_numbering_ready()
            self.path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValidationError):
                require_numbering_ready()
            self.path.unlink()
            with self.assertRaises(ValidationError):
                require_numbering_ready()

    def test_restores_same_department_id_registration_and_a05_then_replay(self):
        department_id = self.department.pk
        self.audit.delete()
        self.registration.delete()
        self.department.delete()
        with self.assertRaises(NumberingLedgerError):
            verify_snapshot(self.path)
        restore_departments(path=self.path, actor=self.manager)
        verify_snapshot(self.path)
        self.assertEqual(Department.objects.get(pk=department_id).name, "新部署")
        self.assertEqual(DepartmentRegistration.objects.get(department_id=department_id).operation_id,
                         self.operation_id)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.DEPARTMENT_CREATE).count(), 1)
        self.client.force_login(self.manager)
        create_form = self.client.get(reverse("management:employee_create"))
        self.assertContains(create_form, "新部署")
        response = self.client.post(reverse("management:department_create"), {
            "name": "新部署", "code": "3", "is_active": "on", "operation_id": str(self.operation_id),
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Department.objects.count(), 1)
        self.assertEqual(DepartmentRegistration.objects.count(), 1)

    def test_missing_issued_number_history_restores_when_employee_matches(self):
        employee = get_user_model().objects.create_user(
            employee_number="30001", password="TestPassword_2026!",
        )
        history = EmployeeNumberHistory.objects.create(
            employee=employee, department=self.department, employee_number="30001",
        )
        export_snapshot(self.path)
        history.delete()
        restore_departments(path=self.path, actor=self.manager)
        verify_snapshot(self.path)
        self.assertTrue(EmployeeNumberHistory.objects.filter(
            employee=employee, employee_number="30001",
        ).exists())

    def test_changed_employee_number_prevents_history_restore(self):
        employee = get_user_model().objects.create_user(
            employee_number="30001", password="TestPassword_2026!",
        )
        history = EmployeeNumberHistory.objects.create(
            employee=employee, department=self.department, employee_number="30001",
        )
        export_snapshot(self.path)
        history.delete()
        employee.employee_number = "30002"
        employee.save(update_fields=["employee_number"])
        with self.assertRaisesRegex(NumberingLedgerError, "発行済み番号"):
            restore_departments(path=self.path, actor=self.manager)

    def test_restores_old_number_history_after_department_transfer(self):
        new_department = Department.objects.create(name="異動先", code=4)
        employee = get_user_model().objects.create_user(
            employee_number="40001", password="TestPassword_2026!", department="異動先",
        )
        old_history = EmployeeNumberHistory.objects.create(
            employee=employee, department=self.department, employee_number="30001",
        )
        current_history = EmployeeNumberHistory.objects.create(
            employee=employee, department=new_department, employee_number="40001",
        )
        export_snapshot(self.path)
        old_history_id = old_history.pk
        old_history.delete()

        restore_departments(path=self.path, actor=self.manager)

        verify_snapshot(self.path)
        self.assertEqual(
            EmployeeNumberHistory.objects.get(pk=old_history_id).employee_number, "30001"
        )
        self.assertTrue(EmployeeNumberHistory.objects.filter(pk=current_history.pk).exists())

    def test_a07_updates_external_ledger_after_commit(self):
        self.client.force_login(self.manager)
        with override_settings(NUMBERING_LEDGER_PATH=self.path), patch(
            "management.numbering_ledger._test_database", return_value=False
        ):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse("management:department_create"), {
                    "name": "第2部署", "code": "4", "is_active": "on",
                    "operation_id": str(uuid.uuid4()),
                })
            self.assertEqual(response.status_code, 302)
            verify_snapshot(self.path)
            self.assertEqual(len(verify_snapshot(self.path)["departments"]), 2)

    def test_unfinished_reservation_stops_new_numbering(self):
        with override_settings(NUMBERING_LEDGER_PATH=self.path), patch(
            "management.numbering_ledger._test_database", return_value=False
        ):
            reserve_pending(kind="department_create", value=4,
                            actor_id=self.manager.pk, operation_id=uuid.uuid4())
            self.assertEqual(read_snapshot(self.path)["pending"][0]["value"], "4")
            with self.assertRaises(ValidationError):
                require_numbering_ready()
            with self.assertRaisesRegex(NumberingLedgerError, "確定結果"):
                reconcile_pending(path=self.path, actor=self.manager, reason="復旧確認")

    def test_rolled_back_reservation_is_cleared_only_after_db_matches(self):
        operation_id = uuid.uuid4()
        with override_settings(NUMBERING_LEDGER_PATH=self.path), patch(
            "management.numbering_ledger._test_database", return_value=False
        ):
            reserve_pending(kind="department_create", value=4,
                            actor_id=self.manager.pk, operation_id=operation_id)
            self.assertTrue(cancel_pending(kind="department_create",
                                           operation_id=operation_id))
            verify_snapshot(self.path)

    def test_a07_audit_failure_rolls_back_pending_reservation(self):
        self.client.force_login(self.manager)
        with override_settings(NUMBERING_LEDGER_PATH=self.path), patch(
            "management.numbering_ledger._test_database", return_value=False
        ), patch("management.department_views.AuditLog.objects.create",
                 side_effect=IntegrityError("simulated audit failure")):
            response = self.client.post(reverse("management:department_create"), {
                "name": "第2部署", "code": "4", "is_active": "on",
                "operation_id": str(uuid.uuid4()),
            })
        self.assertEqual(response.status_code, 409)
        verify_snapshot(self.path)
        self.assertEqual(Department.objects.count(), 1)

    def test_committed_operation_with_pending_reservation_can_be_reconciled(self):
        self.client.force_login(self.manager)
        operation_id = uuid.uuid4()
        with override_settings(NUMBERING_LEDGER_PATH=self.path), patch(
            "management.numbering_ledger._test_database", return_value=False
        ), patch("management.department_views.sync_after_commit"):
            response = self.client.post(reverse("management:department_create"), {
                "name": "第2部署", "code": "4", "is_active": "on",
                "operation_id": str(operation_id),
            })
            self.assertEqual(response.status_code, 302)
            with self.assertRaises(ValidationError):
                require_numbering_ready()
            with self.captureOnCommitCallbacks(execute=True):
                reconcile_pending(path=self.path, actor=self.manager,
                                  reason="DBの登録結果と保全記録を照合して再開")
            verify_snapshot(self.path)
            self.assertTrue(AuditLog.objects.filter(
                target_model="NumberingLedger", reason="DBの登録結果と保全記録を照合して再開",
            ).exists())

    def test_committed_employee_number_with_pending_reservation_can_be_reconciled(self):
        self.client.force_login(self.manager)
        operation_id = uuid.uuid4()
        with override_settings(NUMBERING_LEDGER_PATH=self.path), patch(
            "management.numbering_ledger._test_database", return_value=False
        ), patch("management.views.sync_after_commit"):
            response = self.client.post(reverse("management:employee_create"), {
                "first_name": "太郎", "last_name": "佐藤",
                "department_choice": str(self.department.pk),
                "hire_date": "2026-04-01", "operation_id": str(operation_id),
            })
            self.assertEqual(response.status_code, 200)
            self.assertTrue(EmployeeNumberHistory.objects.filter(
                employee_number="30001"
            ).exists())
            with self.assertRaises(ValidationError):
                require_numbering_ready()
            with self.captureOnCommitCallbacks(execute=True):
                reconcile_pending(path=self.path, actor=self.manager,
                                  reason="発行済み社員番号をDBと照合して再開")
            verify_snapshot(self.path)


# リリース受入条件

"""v1.4 リリース修正の受入テスト。"""

import csv
from datetime import date, datetime
from io import StringIO
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from attendance.models import WorkSession
from auditlog.models import AuditLog
from management.models import (
    Department,
    EmploymentInfo,
    ExportBatch,
)
from management.services import (
    finalize_month,
    reopen_month,
)
from notifications.models import Notification


class ReleaseAcceptanceTests(TestCase):
    """リリース受入テスト。"""

    def setUp(self):
        Employee = get_user_model()

        self.manager = Employee.objects.create_user(
            employee_number="91001",
            password="ManagerPass_2026!",
            is_business_admin=True,
        )

        self.employee = Employee.objects.create_user(
            employee_number="91002",
            password="EmployeePass_2026!",
            first_name="花子",
            last_name="山田",
        )

        self.client.force_login(self.manager)

    def test_registration_and_reset_are_one_time_and_not_cached(self):
        """社員登録と初期パスワード再発行の受入テスト。"""

        # テスト専用DBに部署を登録する。
        department = Department.objects.create(
            name="営業部",
            code=1,
            is_active=True,
        )

        # 社員登録。
        create = self.client.post(
            reverse("management:employee_create"),
            {
                "first_name": "太郎",
                "last_name": "佐藤",
                "department_choice": str(department.pk),
                "hire_date": "2026-04-01",
            },
        )

        self.assertEqual(create.status_code, 200)

        # 社員登録に失敗した場合、
        # 原因を確認できるようにする。
        created_exists = (
            get_user_model().objects.filter(employee_number="10001").exists()
        )

        if not created_exists:
            form = None

            if create.context:
                form = create.context.get("form")

            errors = (
                form.errors.as_json()
                if form is not None
                else "フォームエラーを取得できませんでした。"
            )

            self.fail("社員登録に失敗しました。" f" フォームエラー: {errors}")

        self.assertContains(
            create,
            "初期パスワード",
        )

        self.assertIn(
            "no-store",
            create["Cache-Control"],
        )

        created = get_user_model().objects.get(employee_number="10001")

        # 所属部署の保存確認。
        self.assertEqual(
            created.department,
            "営業部",
        )

        # 初期パスワード再発行の確認画面。
        reset_url = reverse(
            "management:employee_password_reset",
            args=[created.pk],
        )

        confirm = self.client.get(reset_url)

        self.assertEqual(
            confirm.status_code,
            200,
        )

        self.assertContains(
            confirm,
            "再発行の確認",
        )

        ticket = confirm.context["ticket"]

        # 初期パスワードを再発行する。
        reset = self.client.post(
            reset_url,
            {
                "ticket": ticket,
                "confirm": "yes",
            },
        )

        self.assertEqual(
            reset.status_code,
            200,
        )

        self.assertContains(
            reset,
            "初期パスワード再発行が完了",
        )

        self.assertIn(
            "no-store",
            reset["Cache-Control"],
        )

        # 同一チケットの再利用を禁止する。
        replay = self.client.post(
            reset_url,
            {
                "ticket": ticket,
                "confirm": "yes",
            },
        )

        self.assertEqual(
            replay.status_code,
            400,
        )

        self.assertNotIn(
            "初期パスワード再発行が完了",
            replay.content.decode(),
        )

    def test_month_notifications_for_finalize_reopen_refinalize(self):
        """月次確定・再開・再確定の通知テスト。"""

        month = date(2026, 9, 1)

        args = {
            "manager_id": self.manager.pk,
            "employee_id": self.employee.pk,
            "target_month": month,
        }

        finalize_month(
            **args,
            checked_no_record=True,
        )

        reopen_month(
            **args,
            reason="再確認が必要",
        )

        finalize_month(
            **args,
            checked_no_record=True,
        )

        kinds = list(
            Notification.objects.filter(recipient=self.employee)
            .order_by("created_at", "pk")
            .values_list("kind", flat=True)
        )

        self.assertEqual(
            kinds,
            [
                Notification.Kind.MONTH_FINALIZED,
                Notification.Kind.MONTH_REOPENED,
                Notification.Kind.MONTH_FINALIZED,
            ],
        )

    def test_csv_schema_values_and_employment_period(self):
        """CSV出力と在籍期間の受入テスト。"""

        month = date(2026, 9, 1)
        jst = ZoneInfo("Asia/Tokyo")

        WorkSession.objects.create(
            employee=self.employee,
            work_date=date(2026, 9, 15),
            clock_in_at=datetime(
                2026,
                9,
                15,
                9,
                tzinfo=jst,
            ),
            clock_out_at=datetime(
                2026,
                9,
                15,
                18,
                tzinfo=jst,
            ),
            status=WorkSession.Status.COMPLETED,
        )

        EmploymentInfo.objects.create(
            employee=self.employee,
            department="営業部",
            hire_date=date(2026, 9, 15),
            leave_date=date(2026, 9, 20),
        )

        finalize_month(
            manager_id=self.manager.pk,
            employee_id=self.employee.pk,
            target_month=month,
            checked_no_record=True,
        )

        base = {
            "month": "2026-09",
            "scope": "employee",
            "department": "",
            "employee_number": self.employee.employee_number,
            "mode": "download",
        }

        created = self.client.post(
            reverse("management:bulk_export"),
            {
                **base,
                "output_format": "daily",
            },
        )

        self.assertEqual(
            created.status_code,
            302,
        )

        batch = ExportBatch.objects.get()

        daily = self.client.post(
            reverse(
                "management:batch_download",
                args=[
                    batch.output_id,
                    "daily",
                ],
            )
        )

        self.assertEqual(
            daily.status_code,
            200,
        )

        self.assertTrue(daily.content.startswith(b"\xef\xbb\xbf"))

        self.assertIn(
            b"\r\n",
            daily.content,
        )

        daily_rows = list(csv.reader(StringIO(daily.content.decode("utf-8-sig"))))

        self.assertEqual(
            daily_rows[0],
            [
                "社員番号",
                "氏名",
                "部署",
                "勤務日",
                "出勤日時",
                "退勤日時",
                "休憩秒数",
                "実働秒数",
                "記録状態",
                "確定状態",
                "データ版",
            ],
        )

        self.assertEqual(
            len(daily_rows),
            7,
        )

        self.assertEqual(
            daily_rows[1][4:6],
            [
                "2026-09-15 09:00:00",
                "2026-09-15 18:00:00",
            ],
        )

        self.assertEqual(
            daily_rows[1][7],
            "32400",
        )

        monthly = self.client.post(
            reverse(
                "management:batch_download",
                args=[
                    batch.output_id,
                    "monthly",
                ],
            )
        )

        self.assertEqual(
            monthly.status_code,
            200,
        )

        monthly_rows = list(csv.reader(StringIO(monthly.content.decode("utf-8-sig"))))

        self.assertEqual(
            monthly_rows[0],
            [
                "社員番号",
                "氏名",
                "部署",
                "対象月",
                "勤務記録日数",
                "実働秒数合計",
                "休憩秒数合計",
                "未完了件数",
                "確定日時",
                "データ版",
            ],
        )

        self.assertEqual(
            monthly_rows[1][4:8],
            [
                "1",
                "32400",
                "0",
                "0",
            ],
        )

        exports = list(
            AuditLog.objects.filter(
                action=AuditLog.Action.CSV_EXPORT,
                target_model="ExportBatch",
                target_id=str(batch.output_id),
            ).order_by("pk")
        )

        self.assertEqual(
            [item.details["format"] for item in exports],
            [
                "daily",
                "monthly",
            ],
        )

        self.assertTrue(
            all(item.details["output_id"] == str(batch.output_id) for item in exports)
        )

    def test_role_change_and_login_failure_are_audited(self):
        """権限変更とログイン失敗の監査テスト。"""

        self.employee.is_business_admin = True

        self.employee.save(
            update_fields=[
                "is_business_admin",
            ]
        )

        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.ROLE_CHANGE,
                target_employee=self.employee,
            ).exists()
        )

        self.client.logout()

        self.client.post(
            reverse("accounts:login"),
            {
                "username": self.employee.employee_number,
                "password": "incorrect-password",
            },
        )

        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.Action.AUTH_FAILURE).exists()
        )


# 要件定義書 v1.5.7 との照合で見つかった差異の修正

import csv as _csv
import io as _io
import os as _os
import subprocess as _subprocess
import sys as _sys
import tempfile as _tempfile
from datetime import date as _date, datetime as _datetime
from zoneinfo import ZoneInfo as _ZoneInfo

from django.conf import settings as _settings
from django.contrib.auth import get_user_model as _get_user_model
from django.core.exceptions import ValidationError as _ValidationError
from django.test import SimpleTestCase as _SimpleTestCase, TestCase as _TestCase
from django.urls import reverse as _reverse

from attendance.models import WorkSession as _WorkSession
from management.models import Department as _Department, ExportBatch as _ExportBatch
from management.role_management import (
    RoleChangeError as _RoleChangeError,
    change_business_admin_role as _change_business_admin_role,
)
from management.services import finalize_month as _finalize_month


class RequirementV157ConformanceTests(_TestCase):
    password = "TestPassword_2026!"

    def setUp(self):
        Employee = _get_user_model()
        self.manager = Employee.objects.create_user(
            employee_number="91001", password=self.password, is_business_admin=True,
        )
        self.second_manager = Employee.objects.create_user(
            employee_number="91002", password=self.password, is_business_admin=True,
        )
        # 技術管理用アカウント（業務管理者権限が付いていても人数に含めない）。
        self.technical = Employee.objects.create_superuser(
            employee_number="99001", password=self.password, is_business_admin=True,
        )

    # ---- 差異1：A04 の CSV は出力IDを発行し、確定版から日次・月次を取得する ----

    def test_a04_csv_button_issues_output_id_and_monthly_totals_header(self):
        employee = _get_user_model().objects.create_user(
            employee_number="10001", password=self.password, hire_date=_date(2026, 1, 1),
        )
        jst = _ZoneInfo("Asia/Tokyo")
        _WorkSession.objects.create(
            employee=employee, work_date=_date(2026, 9, 15),
            clock_in_at=_datetime(2026, 9, 15, 9, tzinfo=jst),
            clock_out_at=_datetime(2026, 9, 15, 18, tzinfo=jst),
            status=_WorkSession.Status.COMPLETED,
        )
        _finalize_month(manager_id=self.manager.pk, employee_id=employee.pk,
                        target_month=_date(2026, 9, 1), checked_no_record=True)
        self.client.force_login(self.manager)

        response = self.client.post(_reverse("management:month_csv", args=[employee.pk, 2026, 9]))
        batch = _ExportBatch.objects.get()
        self.assertRedirects(response, _reverse("management:batch_detail", args=[batch.output_id]))

        monthly = self.client.post(_reverse("management:batch_download", args=[batch.output_id, "monthly"]))
        self.assertIn(str(batch.output_id), monthly["Content-Disposition"])
        rows = list(_csv.reader(_io.StringIO(monthly.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0], [
            "社員番号", "氏名", "部署", "対象月", "勤務記録日数", "実働秒数合計",
            "休憩秒数合計", "未完了件数", "確定日時", "データ版",
        ])
        self.assertEqual(rows[1][5], "32400")

    def test_legacy_direct_csv_view_is_removed(self):
        from management import views
        self.assertFalse(hasattr(views, "month_csv"))

    # ---- 差異5：PC の管理者メニュー「運用メニュー」に C02 ----

    def test_admin_sidebar_operations_menu_has_account_and_guide(self):
        self.client.force_login(self.manager)
        html = self.client.get(_reverse("management:audit_history")).content.decode()
        sidebar = html[html.index('<nav class="side-navigation"'):]
        sidebar = sidebar[:sidebar.index("</nav>")]
        operations = sidebar[sidebar.index("運用メニュー"):]
        self.assertIn(f'href="{_reverse("accounts:overview")}"', operations)
        self.assertIn("アカウントと使い方", operations)

    # ---- 差異6：技術管理用アカウントは有効な業務管理者の人数に含めない ----

    def test_role_revocation_does_not_count_technical_account(self):
        with self.assertRaises(_RoleChangeError):
            _change_business_admin_role(
                actor_id=self.manager.pk, employee_id=self.second_manager.pk,
                grant=False, expected_role=True, reason="交代",
            )
        self.second_manager.refresh_from_db()
        self.assertTrue(self.second_manager.is_business_admin)

    def test_model_guard_does_not_count_technical_account(self):
        self.second_manager.is_active = False
        with self.assertRaises(_ValidationError):
            self.second_manager.save()
        # 技術管理用アカウント自身は対象外のため、人数条件に関係なく変更できる。
        self.technical.is_business_admin = False
        self.technical.save()

    def test_deactivation_does_not_count_technical_account(self):
        department = _Department.objects.create(name="総務部", code=1)
        _get_user_model().objects.filter(pk=self.second_manager.pk).update(department="総務部")
        self.client.force_login(self.manager)
        url = _reverse("management:employee_edit", args=[self.second_manager.pk])
        response = self.client.post(url, {
            "employee_number": "91002", "first_name": "Test", "last_name": "Manager",
            "department_choice": str(department.pk), "change_reason": "退職",
            "edit_state": self.client.get(url).context["edit_state"],
            "operation_id": "8d3f1b9e-2c55-4c1f-9f1a-7f2d6c3b9a10",
        })
        self.assertContains(response, "有効な管理者は2人以上必要です。")
        self.second_manager.refresh_from_db()
        self.assertTrue(self.second_manager.is_active)

    # ---- C01：画面設計の文言 ----

    def test_login_failure_uses_common_message(self):
        response = self.client.post(_reverse("accounts:login"), {
            "username": "91001", "password": "wrong-password",
        })
        self.assertContains(response, "社員番号またはパスワードを確認してください。")
        _get_user_model().objects.filter(pk=self.second_manager.pk).update(is_active=False)
        response = self.client.post(_reverse("accounts:login"), {
            "username": "91002", "password": self.password,
        })
        # 停止状態は明かさず、同じ文言で案内する（11章）。
        self.assertContains(response, "社員番号またはパスワードを確認してください。")

    def test_login_page_has_design_links_and_toggle_label(self):
        response = self.client.get(_reverse("accounts:login"))
        self.assertContains(response, "勤怠管理システムにログインしてください。")
        self.assertContains(response, 'href="#login-contact"')
        self.assertContains(response, 'id="login-trouble"')
        self.assertContains(response, "ログインできない場合")
        self.assertContains(response, "社内問い合わせ窓口")
        self.assertContains(response, "表示する")


class ProductionSQLiteSettingsTests(_SimpleTestCase):
    """差異2：本番設定は SQLite（IMMEDIATE）で、配置先を検証する（11章）。"""

    def load(self, sqlite_path=None):
        env = {
            **_os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings_production",
            "DJANGO_SECRET_KEY": "s" * 60,
            "DJANGO_ALLOWED_HOSTS": "example.com",
            "PYTHONIOENCODING": "utf-8",
        }
        env.pop("DJANGO_SQLITE_PATH", None)
        if sqlite_path is not None:
            env["DJANGO_SQLITE_PATH"] = sqlite_path
        code = (
            "import django; django.setup(); from django.conf import settings as s; "
            "d = s.DATABASES['default']; "
            "print(d['ENGINE'], d['OPTIONS']['transaction_mode'], d['OPTIONS']['timeout']); "
            "print(d['NAME'])"
        )
        return _subprocess.run(
            [_sys.executable, "-c", code], cwd=_settings.BASE_DIR, env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )

    def test_valid_local_path_uses_sqlite_immediate(self):
        with _tempfile.TemporaryDirectory() as directory:
            result = self.load(_os.path.join(directory, "attendance.sqlite3"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0].split(),
                         ["django.db.backends.sqlite3", "IMMEDIATE", "20"])

    def test_default_is_project_db_sqlite3(self):
        result = self.load()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0].split(),
                         ["django.db.backends.sqlite3", "IMMEDIATE", "20"])
        self.assertEqual(result.stdout.splitlines()[1],
                         str((_settings.BASE_DIR / "db.sqlite3").resolve()))

    def test_rejects_unsafe_locations(self):
        with _tempfile.TemporaryDirectory() as directory:
            cases = [
                "attendance.sqlite3",
                "//fileserver/share/attendance.sqlite3",
                str(_settings.BASE_DIR / "static" / "attendance.sqlite3"),
                _os.path.join(directory, "missing", "attendance.sqlite3"),
            ]
            for path in cases:
                with self.subTest(path=path):
                    result = self.load(path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("ImproperlyConfigured", result.stderr)

    def test_postgresql_is_not_configured_anywhere(self):
        """SQLite（db.sqlite3）に一本化し、PostgreSQL の設定・依存・スクリプトを残さない。"""
        base = _settings.BASE_DIR
        self.assertFalse((base / "scripts" / "backup_postgres.py").exists())
        self.assertNotIn("psycopg", (base / "requirements.txt").read_text(encoding="utf-8"))
        for name in ("settings.py", "settings_production.py", "settings_test.py"):
            text = (base / "config" / name).read_text(encoding="utf-8")
            self.assertNotIn("postgresql", text, name)
            self.assertNotIn("POSTGRES_", text, name)


"""要件定義書 v1.5.7 の受入条件のうち、個別のテストがなかった項目（T11・T13・T19）。"""

import re as _re
from datetime import date as _date, datetime as _datetime
from zoneinfo import ZoneInfo as _ZoneInfo

from django.contrib.auth import get_user_model as _get_user_model
from django.test import RequestFactory as _RequestFactory, TestCase as _AcceptanceTestCase
from django.urls import reverse as _reverse


class RequirementGapAcceptanceTests(_AcceptanceTestCase):
    def setUp(self):
        Employee = _get_user_model()
        self.manager = Employee.objects.create_user(
            employee_number="95001", password="TestPassword_2026!",
            first_name="管理", last_name="担当", is_business_admin=True,
            hire_date=_date(2024, 1, 1),
        )
        self.employee = Employee.objects.create_user(
            employee_number="95002", password="TestPassword_2026!",
            first_name="花子", last_name="山田", hire_date=_date(2024, 1, 1),
        )

    # ---------- T11: 26人以上でもページ切替で集計値が変わらない ----------
    def test_t11_a01_totals_and_chart_are_same_on_every_page_with_26_or_more_employees(self):
        from attendance.models import WorkSession
        from management.templatetags.a01_dashboard import a01_snapshot

        Employee = _get_user_model()
        jst = _ZoneInfo("Asia/Tokyo")
        for index in range(27):
            person = Employee.objects.create_user(
                employee_number=f"96{index:03d}", password="TestPassword_2026!",
                first_name=f"社員{index}", last_name="検証", hire_date=_date(2024, 1, 1),
            )
            day = 1 + index % 9
            WorkSession.objects.create(
                employee=person, work_date=_date(2026, 10, day),
                clock_in_at=_datetime(2026, 10, day, 9, tzinfo=jst),
                status=WorkSession.Status.WORKING,
            )

        def snapshot(page):
            request = _RequestFactory().get("/management/attendance/", {"month": "2026-10", "page": page})
            request.user = self.manager
            return a01_snapshot({"request": request})

        first, second = snapshot(1), snapshot(2)
        self.assertEqual(len(first["page_obj"].object_list), 25)
        self.assertGreaterEqual(len(second["page_obj"].object_list), 1)
        self.assertGreaterEqual(first["employee_count"], 26)
        for key in ("employee_count", "incomplete_count", "pending_count", "finalized_count", "incomplete_chart"):
            with self.subTest(key=key):
                self.assertEqual(first[key], second[key])
        self.assertEqual(first["incomplete_count"], 27)

    # ---------- T13: 審査中の代理申請がある間は再有効化できない ----------
    def test_t13_reactivation_is_rejected_while_proxy_request_is_pending(self):
        from corrections.models import CorrectionRequest
        from corrections.services import submit_correction, withdraw_correction
        from management.models import Department

        jst = _ZoneInfo("Asia/Tokyo")
        department = Department.objects.create(name="総務", code=1, is_active=True)
        self.employee.department = department.name
        self.employee.is_active = False
        self.employee.save()
        day = _date(2025, 10, 6)
        proxy = submit_correction(
            employee_id=self.employee.pk, actor_id=self.manager.pk,
            work_day=day, expected_version=0,
            proposal={
                "clock_in_at": _datetime(2025, 10, 6, 9, tzinfo=jst).isoformat(),
                "clock_out_at": _datetime(2025, 10, 6, 18, tzinfo=jst).isoformat(),
                "breaks": [],
            },
            reason="打刻漏れ", proxy_reason="本人は利用停止中",
            evidence="勤務表を担当者が照合",
        )
        self.assertTrue(proxy.is_proxy)

        self.client.force_login(self.manager)
        edit_url = _reverse("management:employee_edit", args=[self.employee.pk])

        def reactivate():
            edit_state = self.client.get(edit_url).context["edit_state"]
            return self.client.post(edit_url, {
                "employee_number": self.employee.employee_number,
                "first_name": "花子", "last_name": "山田",
                "department_choice": str(department.pk),
                "is_active": "on", "change_reason": "本人の復職",
                "edit_state": edit_state,
            })

        response = reactivate()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "審査中の代理申請を処理または取下げてください。")
        self.employee.refresh_from_db()
        self.assertFalse(self.employee.is_active)

        withdraw_correction(employee_id=self.manager.pk, request_id=proxy.pk)
        self.assertEqual(
            CorrectionRequest.objects.get(pk=proxy.pk).status, CorrectionRequest.Status.WITHDRAWN,
        )
        self.assertEqual(reactivate().status_code, 302)
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.is_active)

    # ---------- T19: 階層メニューと現在地 ----------
    def _sidebar(self, response):
        html = response.content.decode()
        match = _re.search(r'<nav class="side-navigation".*?</nav>', html, _re.S)
        self.assertIsNotNone(match, "サイドバーが見つかりません。")
        return match.group(0)

    def test_t19_employee_menu_shows_hierarchy_and_current_location(self):
        self.client.force_login(self.employee)
        sidebar = self._sidebar(self.client.get(_reverse("attendance:daily", args=[2026, 11, 2])))
        self.assertIn('aria-label="社員メニュー"', sidebar)
        for label in ("打刻メニュー", "勤怠メニュー", "アカウントメニュー"):
            self.assertIn(label, sidebar)
        self.assertNotIn("管理者メニュー", sidebar)
        self.assertNotIn("勤怠管理", sidebar)
        # 日別詳細を開いている間は親画面「自分の勤怠」を現在地として示す。
        current = _re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', sidebar)
        self.assertEqual(current, [_reverse("attendance:monthly")])
        self.assertIn("side-link--current", sidebar)

    def test_t19_manager_menu_shows_hierarchy_and_current_location(self):
        self.client.force_login(self.manager)
        sidebar = self._sidebar(self.client.get(_reverse("management:employees")))
        self.assertIn('aria-label="管理者メニュー"', sidebar)
        for label in ("勤怠管理", "月次管理", "社員・権限管理", "運用メニュー"):
            self.assertIn(label, sidebar)
        current = _re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', sidebar)
        self.assertEqual(current, [_reverse("management:employees")])
        # 一般社員は管理画面へ直接アクセスできない。
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(_reverse("management:employees")).status_code, 403)
