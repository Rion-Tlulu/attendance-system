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

    def __str__(self):
        return self.title
