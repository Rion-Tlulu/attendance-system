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
