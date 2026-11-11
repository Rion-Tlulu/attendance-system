"""業務管理者権限の画面と人数制約。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from auditlog.models import AuditLog
from management.templatetags.a03_directory import a03_directory


class BusinessAdminRoleTests(TestCase):
    def setUp(self):
        Employee = get_user_model()
        self.manager = Employee.objects.create_user(
            employee_number="91001", password="TestPassword_2026!",
            is_business_admin=True,
        )
        self.employee = Employee.objects.create_user(
            employee_number="91002", password="TestPassword_2026!",
        )
        self.other = Employee.objects.create_user(
            employee_number="91003", password="TestPassword_2026!",
        )
        self.client.force_login(self.manager)

    def url(self, employee=None):
        return reverse("management:employee_role", args=[(employee or self.employee).pk])

    def data(self, expected="employee", desired="admin", reason="運用担当の承認済み"):
        return {
            "expected_role": expected,
            "desired_role": desired,
            "change_reason": reason,
        }

    def test_sole_manager_can_grant_second_manager_with_audit(self):
        directory = self.client.get(reverse("management:employees"))
        self.assertContains(directory, self.url())
        edit = self.client.get(reverse("management:employee_edit", args=[self.employee.pk]))
        self.assertContains(edit, self.url())
        self.assertContains(self.client.get(self.url()), "業務管理者権限の変更")

        response = self.client.post(self.url(), self.data())
        self.assertEqual(response.status_code, 302)
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.is_business_admin)
        self.assertFalse(self.employee.is_staff)
        self.assertFalse(self.employee.is_superuser)
        role_logs = AuditLog.objects.filter(
            action=AuditLog.Action.ROLE_CHANGE, target_employee=self.employee,
        )
        self.assertEqual(role_logs.count(), 1)
        log = role_logs.get()
        self.assertEqual(log.actor_id, self.manager.pk)
        self.assertEqual(log.reason, "運用担当の承認済み")
        self.assertEqual(log.before_data["is_business_admin"], False)
        self.assertEqual(log.after_data["is_business_admin"], True)
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse("management:home")).status_code, 200)

    def test_cannot_revoke_one_of_only_two_active_managers(self):
        self.client.post(self.url(), self.data())
        response = self.client.post(self.url(), self.data(
            expected="admin", desired="employee", reason="管理者交代",
        ))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2人以上")
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.is_business_admin)
        self.assertEqual(AuditLog.objects.filter(
            action=AuditLog.Action.ROLE_CHANGE, target_employee=self.employee,
        ).count(), 1)

    def test_third_manager_can_be_revoked_but_not_self(self):
        self.client.post(self.url(), self.data())
        self.other.is_business_admin = True
        self.other.save(update_fields=["is_business_admin"])
        response = self.client.post(self.url(), self.data(
            expected="admin", desired="employee", reason="交代済み",
        ))
        self.assertEqual(response.status_code, 302)
        self.employee.refresh_from_db()
        self.assertFalse(self.employee.is_business_admin)
        self.assertEqual(get_user_model().objects.filter(
            is_active=True, is_business_admin=True,
        ).count(), 2)
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse("management:home")).status_code, 403)
        self.client.force_login(self.manager)
        own = self.client.post(self.url(self.manager), self.data(
            expected="admin", desired="employee", reason="自分を取消",
        ))
        self.assertContains(own, "自分自身の業務管理者権限")
        self.manager.refresh_from_db()
        self.assertTrue(self.manager.is_business_admin)

    def test_inactive_and_technical_accounts_cannot_be_granted(self):
        self.employee.is_active = False
        self.employee.save(update_fields=["is_active"])
        self.assertContains(self.client.post(self.url(), self.data()), "利用停止中")
        self.employee.refresh_from_db()
        self.assertFalse(self.employee.is_business_admin)

        self.other.is_staff = True
        self.other.save(update_fields=["is_staff"])
        self.assertContains(self.client.post(self.url(self.other), self.data()), "技術管理用")
        self.other.refresh_from_db()
        self.assertFalse(self.other.is_business_admin)

    def test_stale_form_and_missing_reason_are_rejected(self):
        self.assertContains(self.client.post(self.url(), self.data(reason="")), "変更理由")
        self.employee.is_business_admin = True
        self.employee.save(update_fields=["is_business_admin"])
        response = self.client.post(self.url(), self.data())
        self.assertContains(response, "再読み込み")

    def test_ordinary_employee_is_forbidden_and_csrf_is_required(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.client.post(self.url(), self.data()).status_code, 403)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.manager)
        self.assertEqual(client.post(self.url(), self.data()).status_code, 403)

    def test_audit_failure_rolls_back_role_grant(self):
        with patch("accounts.signals.AuditLog.objects.create", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.url(), self.data())
        self.employee.refresh_from_db()
        self.assertFalse(self.employee.is_business_admin)

    def test_directory_manager_count_excludes_inactive_accounts(self):
        self.other.is_business_admin = True
        self.other.is_active = False
        self.other.save(update_fields=["is_business_admin", "is_active"])
        request = RequestFactory().get(reverse("management:employees"))
        request.user = self.manager
        self.assertEqual(a03_directory({"request": request})["manager_count"], 1)

    def test_employee_edit_still_works_and_cannot_disable_second_manager(self):
        edit_url = reverse("management:employee_edit", args=[self.employee.pk])
        updated = self.client.post(edit_url, {
            "employee_number": self.employee.employee_number,
            "first_name": "更新", "last_name": "社員", "department": "総務",
            "is_active": "on", "change_reason": "",
        })
        self.assertEqual(updated.status_code, 302)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.first_name, "更新")
        self.client.post(self.url(), self.data())
        disabled = self.client.post(edit_url, {
            "employee_number": self.employee.employee_number,
            "first_name": "更新", "last_name": "社員", "department": "総務",
            "change_reason": "管理者交代前の停止試行",
        })
        self.assertContains(disabled, "2人以上")
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.is_active)
