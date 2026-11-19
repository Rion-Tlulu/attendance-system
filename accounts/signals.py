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
def capture_role_before(sender, instance, update_fields=None, **kwargs):
    if update_fields is not None and "is_business_admin" not in update_fields:
        return
    if instance.pk:
        instance._previous_business_admin = sender.objects.filter(pk=instance.pk).values_list(
            "is_business_admin", flat=True
        ).first()


@receiver(post_save, sender=Employee, dispatch_uid="attendance_role_after")
def audit_role_change(sender, instance, created, update_fields=None, **kwargs):
    if update_fields is not None and "is_business_admin" not in update_fields:
        return
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
        reason=getattr(instance, "_role_change_reason", "業務管理者権限の変更"),
        details={},
    )


@receiver(pre_save, sender=Employee, dispatch_uid="attendance_active_before")
def capture_active_before(sender, instance, update_fields=None, **kwargs):
    if update_fields is not None and "is_active" not in update_fields:
        return
    if instance.pk:
        instance._previous_is_active = sender.objects.filter(pk=instance.pk).values_list(
            "is_active", flat=True
        ).first()


@receiver(post_save, sender=Employee, dispatch_uid="attendance_deactivation_sessions")
def end_sessions_on_deactivation(sender, instance, created, update_fields=None, **kwargs):
    """利用停止時は既存セッションを削除し、再有効化後も復活させない（03章・T01）。

    停止の更新と同じトランザクションで削除するため、停止が取り消された場合は
    セッションの削除も取り消される。
    """
    if update_fields is not None and "is_active" not in update_fields:
        return
    if created or getattr(instance, "_previous_is_active", None) is not True or instance.is_active:
        return

    from django.contrib.auth import SESSION_KEY
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    user_id = str(instance.pk)
    stale_keys = [
        session.session_key
        for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator()
        if str(session.get_decoded().get(SESSION_KEY)) == user_id
    ]
    if stale_keys:
        Session.objects.filter(session_key__in=stale_keys).delete()
