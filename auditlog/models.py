
from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditLog(models.Model):
    """業務操作の監査履歴。"""

    class Action(models.TextChoices):
        CLOCK = "clock", "打刻"
        CORRECTION_APPROVE = (
            "correction_approve",
            "修正申請の承認",
        )
        CORRECTION_RETURN = (
            "correction_return",
            "修正申請の差戻し",
        )
        MONTH_FINALIZE = (
            "month_finalize",
            "月次確定",
        )
        MONTH_UNLOCK = (
            "month_unlock",
            "月次確定解除",
        )
        EMPLOYEE_UPDATE = (
            "employee_update",
            "社員情報変更",
        )
        EMPLOYEE_DISABLE = (
            "employee_disable",
            "社員利用無効化",
        )
        CSV_EXPORT = "csv_export", "CSV出力"
        ROLE_CHANGE = "role_change", "権限変更"
        AUTH_FAILURE = "auth_failure", "認証失敗"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="performed_audits",
        verbose_name="実行者",
    )

    target_employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="targeted_audits",
        verbose_name="対象社員",
    )

    action = models.CharField(
        "操作種別",
        max_length=40,
        choices=Action.choices,
    )

    target_model = models.CharField(
        "対象モデル",
        max_length=100,
        blank=True,
    )

    target_id = models.CharField(
        "対象レコードID",
        max_length=100,
        blank=True,
    )

    before_data = models.JSONField(
        "変更前",
        default=dict,
    )

    after_data = models.JSONField(
        "変更後",
        default=dict,
    )

    reason = models.TextField(
        "理由",
        blank=True,
    )

    details = models.JSONField(
        "補足情報",
        default=dict,
    )

    occurred_at = models.DateTimeField(
        "実行日時",
        default=timezone.now,
        editable=False,
    )

    class Meta:
        verbose_name = "操作履歴"
        verbose_name_plural = "操作履歴"
        ordering = ["-occurred_at"]

        indexes = [
            models.Index(
                fields=["-occurred_at"],
                name="audit_occurred_idx",
            ),
            models.Index(
                fields=["action", "-occurred_at"],
                name="audit_action_date_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_action_display()}"
            f" / {self.occurred_at}"
        )
