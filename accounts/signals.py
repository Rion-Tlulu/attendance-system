"""認証失敗と業務管理者権限変更の監査。"""

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_login_failed
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from auditlog.models import AuditLog
from .audit_context import current_actor

Employee = get_user_model()


@receiver(user_login_failed, dispatch_uid="attendance_auth_failure_audit")
def audit_login_failure(sender, credentials, request, **kwargs):
    employee_number = str(credentials.get("employee_number") or credentials.get("username") or "")[:20]
    AuditLog.objects.create(
        action=AuditLog.Action.AUTH_FAILURE,
        target_model="Employee",
        target_id=employee_number,
        before_data={},
        after_data={"authenticated": False},
        reason="ログイン失敗",
        details={"ip": request.META.get("REMOTE_ADDR", "") if request else ""},
    )


@receiver(pre_save, sender=Employee, dispatch_uid="attendance_role_before")
def capture_role_before(sender, instance, **kwargs):
    if instance.pk:
        instance._previous_business_admin = sender.objects.filter(pk=instance.pk).values_list(
            "is_business_admin", flat=True
        ).first()


@receiver(post_save, sender=Employee, dispatch_uid="attendance_role_after")
def audit_role_change(sender, instance, created, **kwargs):
    previous = getattr(instance, "_previous_business_admin", None)
    if created or previous is None or previous == instance.is_business_admin:
        return
    AuditLog.objects.create(
        actor=current_actor.get(),
        target_employee=instance,
        action=AuditLog.Action.ROLE_CHANGE,
        target_model="Employee",
        target_id=str(instance.pk),
        before_data={"is_business_admin": previous},
        after_data={"is_business_admin": instance.is_business_admin},
        reason="業務管理者権限の変更",
        details={},
    )
