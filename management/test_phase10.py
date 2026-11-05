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
