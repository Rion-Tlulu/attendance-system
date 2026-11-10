from django.contrib.auth import get_user_model
from django.urls import reverse

from .models import Notification


def visible_notifications(user):
    """現在の権限で閲覧できる本人宛通知。"""
    queryset = Notification.objects.filter(recipient=user)
    if not user.is_business_admin:
        queryset = queryset.filter(is_management=False).exclude(
            kind=Notification.Kind.CORRECTION_SUBMITTED
        )
    return queryset


def create_notification(
    *,
    recipient,
    kind,
    title,
    body,
    target_path="",
    event_key=None,
    is_management=False,
):
    """通知重複させずに作成する"""

    if event_key:
        notification, _ = Notification.objects.get_or_create(
            event_key=event_key,
            defaults={
                "recipient": recipient,
                "kind": kind,
                "title": title,
                "body": body,
                "target_path": target_path,
                "is_management": is_management,
            },
        )

        return notification

    return Notification.objects.create(
        recipient=recipient,
        kind=kind,
        title=title,
        body=body,
        target_path=target_path,
        is_management=is_management,
    )


def notify_correction_submitted(correction):
    """申請提出を業務管理者へ通知する"""

    Employee = get_user_model()

    managers = Employee.objects.filter(
        is_active=True,
        is_business_admin=True,
    ).exclude(
        pk=correction.requested_by_id,
    )

    target = reverse(
        "management:correction_detail",
        args=[correction.pk],
    )

    for manager in managers.iterator():
        create_notification(
            recipient=manager,
            kind=Notification.Kind.CORRECTION_SUBMITTED,
            title="新しい修正申請があります",
            body=("社員から勤怠修正申請が提出されました" "内容を確認してください"),
            target_path=target,
            event_key=(f"correction:{correction.pk}:" f"submitted:{manager.pk}"),
            is_management=True,
        )


def notify_correction_reviewed(correction):
    """申請結果を申請者本人へ通知する"""

    status = correction.status

    if status == "approved":
        kind = Notification.Kind.CORRECTION_APPROVED
        title = "修正申請が承認されました"
        body = "提出した勤怠修正申請が承認されました" "修正内容を確認してください"

    elif status == "returned":
        kind = Notification.Kind.CORRECTION_RETURNED
        title = "修正申請が差し戻されました"
        body = (
            "提出した勤怠修正申請が差し戻されました" "理由と申請内容を確認してください"
        )

    else:
        return None

    return create_notification(
        recipient=correction.requested_by,
        kind=kind,
        title=title,
        body=body,
        target_path=reverse(
            "corrections:detail",
            args=[correction.pk],
        ),
        event_key=(
            f"correction:{correction.pk}" f"{status}:{correction.requested_by_id}"
        ),
    )


def notify_month_changed(closing):
    """月次確定・解除を対象社員本人へ通知する。呼び出し元のトランザクションで保存する。"""
    from attendance.models import MonthlyClosing

    finalized = closing.status == MonthlyClosing.Status.FINALIZED
    kind = (
        Notification.Kind.MONTH_FINALIZED
        if finalized else Notification.Kind.MONTH_REOPENED
    )
    month = closing.target_month
    return create_notification(
        recipient=closing.employee,
        kind=kind,
        title="月次勤怠が確定しました" if finalized else "月次勤怠の確定が解除されました",
        body=f"{month:%Y年%m月}の勤怠を確認してください。",
        target_path=reverse("attendance:monthly") + f"?month={month:%Y-%m}",
        event_key=f"closing:{closing.pk}:{closing.version}:{closing.employee_id}",
    )
