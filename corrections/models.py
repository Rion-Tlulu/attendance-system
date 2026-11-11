
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
        null=True,
        blank=True,
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="correction_requests",
    )
    work_date = models.DateField()
    related_request = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="followup_requests",
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_corrections",
        verbose_name="申請者",
    )

    original_version = models.PositiveIntegerField(
        "申請元のデータ版",
        null=True,
        blank=True,
    )

    proposal = models.JSONField(
        "修正案",
        default=dict,
    )

    reason = models.CharField(
        "申請理由",
        max_length=500,
    )

    is_proxy = models.BooleanField("代理申請", default=False)
    proxy_reason = models.CharField("本人申請ができない理由", max_length=1000, blank=True)
    evidence = models.CharField("確認資料と確認方法", max_length=1000, blank=True)

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
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="withdrawn_corrections",
    )
    withdraw_reason = models.CharField("取下げ理由", max_length=500, blank=True)

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
            models.UniqueConstraint(
                fields=["employee", "work_date"],
                condition=models.Q(status="pending"),
                name="unique_pending_correction_day",
            ),
        ]

    def _fill_subject_from_session(self):
        if self.work_session_id:
            session = self.work_session
            if self.employee_id is None:
                self.employee_id = session.employee_id
            if self.work_date is None:
                self.work_date = session.work_date

    def save(self, *args, **kwargs):
        self._fill_subject_from_session()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"employee", "work_date"}
        return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self._fill_subject_from_session()
        if self.employee_id is None or self.work_date is None:
            raise ValidationError("対象社員と勤務日が必要です。")
        if self.work_session_id is None and self.original_version is not None:
            raise ValidationError("元勤務がない申請の元版は空欄にしてください。")

        if (self.requested_by_id and not self.is_proxy
                and self.requested_by_id != self.employee_id):
            raise ValidationError(
                "申請者は対象勤務の本人である必要があります。"
            )

        if self.is_proxy and (not self.proxy_reason.strip() or not self.evidence.strip()):
            raise ValidationError("代理申請の理由と確認資料が必要です。")

        if (
            self.reviewed_by_id
            and self.reviewed_by_id in (
                self.employee_id, self.requested_by_id,
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
            f" / {self.work_date}"
            f" / {self.get_status_display()}"
        )
