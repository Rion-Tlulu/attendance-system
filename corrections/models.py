
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from attendance.models import WorkSession


class CorrectionRequest(models.Model):
    """勤務単位の修正申請。"""

    class Status(models.TextChoices):
        PENDING = "pending", "審査中"
        APPROVED = "approved", "承認済み"
        RETURNED = "returned", "差戻し"
        WITHDRAWN = "withdrawn", "取下げ済み"

    work_session = models.ForeignKey(
        WorkSession,
        on_delete=models.PROTECT,
        related_name="correction_requests",
        verbose_name="対象勤務",
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_corrections",
        verbose_name="申請者",
    )

    original_version = models.PositiveIntegerField(
        "申請元のデータ版",
    )

    proposal = models.JSONField(
        "修正案",
        default=dict,
    )

    reason = models.CharField(
        "申請理由",
        max_length=500,
    )

    status = models.CharField(
        "申請状態",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_corrections",
        verbose_name="処理者",
    )

    reviewed_at = models.DateTimeField(
        "処理日時",
        null=True,
        blank=True,
    )

    return_reason = models.CharField(
        "差戻し理由",
        max_length=500,
        blank=True,
    )

    withdrawn_at = models.DateTimeField(
        "取下げ日時",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        "申請日時",
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        "更新日時",
        auto_now=True,
    )

    class Meta:
        verbose_name = "修正申請"
        verbose_name_plural = "修正申請"
        ordering = ["-created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["work_session"],
                condition=models.Q(status="pending"),
                name="unique_pending_correction",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.work_session_id
            and self.requested_by_id
            and (
                self.requested_by_id
                != self.work_session.employee_id
            )
        ):
            raise ValidationError(
                "申請者は対象勤務の本人である必要があります。"
            )

        if (
            self.reviewed_by_id
            and self.work_session_id
            and (
                self.reviewed_by_id
                == self.work_session.employee_id
            )
        ):
            raise ValidationError({
                "reviewed_by": (
                    "自分の申請を処理することはできません。"
                )
            })

    def __str__(self):
        return (
            f"{self.requested_by.employee_number}"
            f" / {self.work_session.work_date}"
            f" / {self.get_status_display()}"
        )
