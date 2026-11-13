from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    """ログインユーザーごとの通知"""

    class Kind(models.TextChoices):
        CORRECTION_SUBMITTED = (
            "correction_submitted",
            "修正申請の提出",
        )
        CORRECTION_APPROVED = (
            "correction_approved",
            "修正申請の承認",
        )
        CORRECTION_RETURNED = (
            "correction_returned",
            "修正申請の差戻し",
        )
        ATTENDANCE_INCOMPLETE = (
            "attendance_incomplete",
            "未完了勤務",
        )
        GENERAL = (
            "general",
            "一般のお知らせ",
        )
        INCOMPLETE = (
            "incomplete",
            "未完了勤怠のお知らせ",
        )
        MONTH_FINALIZED = (
            "month_finalized",
            "月次確定",
        )
        MONTH_REOPENED = (
            "month_reopened",
            "月次確定解除",
        )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="通知先",
    )

    kind = models.CharField(
        "通知種別",
        max_length=40,
        choices=Kind.choices,
    )

    title = models.CharField(
        "タイトル",
        max_length=120,
    )

    body = models.TextField(
        "本文",
        max_length=1000,
    )

    # reverse()で生成したアプリ内URLを保存
    target_path = models.CharField(
        "移動先",
        max_length=255,
        blank=True,
    )

    is_management = models.BooleanField(
        "管理業務通知",
        default=False,
    )

    # 同じ業務イベントの重複通知を防止
    event_key = models.CharField(
        "イベント識別子",
        max_length=180,
        unique=True,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        "作成日時",
        default=timezone.now,
        editable=False,
    )

    read_at = models.DateTimeField(
        "既読日時",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "通知"
        verbose_name_plural = "通知"

        indexes = [
            models.Index(
                fields=["recipient", "-created_at"],
                name="notify_recipient_date_idx",
            ),
            models.Index(
                fields=["recipient", "read_at"],
                name="notify_recipient_read_idx",
            ),
        ]

    @property
    def is_read(self):
        return self.read_at is not None

    @property
    def is_resolved(self):
        """通知先の現在の業務状態を確認する。"""
        if not self.event_key:
            return False
        if self.kind == self.Kind.INCOMPLETE:
            from attendance.models import IncompleteOccurrence, WorkSession

            parts = self.event_key.split(":")
            if len(parts) >= 4 and not parts[1].isdigit():
                return not IncompleteOccurrence.objects.filter(
                    occurrence_id=parts[1], ended_at__isnull=True,
                ).exists()
            if len(parts) >= 2 and parts[1].isdigit():
                return not WorkSession.objects.filter(
                    pk=int(parts[1]),
                    status__in=(WorkSession.Status.WORKING, WorkSession.Status.ON_BREAK),
                ).exists()
        if self.kind == self.Kind.CORRECTION_SUBMITTED:
            from corrections.models import CorrectionRequest

            parts = self.event_key.split(":")
            if len(parts) >= 2 and parts[1].isdigit():
                return not CorrectionRequest.objects.filter(
                    pk=int(parts[1]), status=CorrectionRequest.Status.PENDING,
                ).exists()
        return False

    @property
    def workflow_label(self):
        if self.kind in (self.Kind.CORRECTION_SUBMITTED, self.Kind.INCOMPLETE, self.Kind.ATTENDANCE_INCOMPLETE):
            return "対応済み" if self.is_resolved else "未対応"
        if self.kind in (self.Kind.CORRECTION_APPROVED, self.Kind.CORRECTION_RETURNED, self.Kind.MONTH_FINALIZED, self.Kind.MONTH_REOPENED):
            return "処理結果"
        return "お知らせ"

    def __str__(self):
        return self.title
