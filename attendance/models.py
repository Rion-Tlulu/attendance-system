
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class WorkSession(models.Model):
    """社員の1勤務日分の勤怠データ。"""

    class Status(models.TextChoices):
        NO_RECORD = "no_record", "記録なし"
        WORKING = "working", "勤務中"
        ON_BREAK = "on_break", "休憩中"
        COMPLETED = "completed", "退勤済み"

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="work_sessions",
        verbose_name="社員",
    )

    work_date = models.DateField(
        "勤務日",
    )

    clock_in_at = models.DateTimeField(
        "有効な出勤日時",
        null=True,
        blank=True,
    )

    clock_out_at = models.DateTimeField(
        "有効な退勤日時",
        null=True,
        blank=True,
    )

    status = models.CharField(
        "勤務状態",
        max_length=20,
        choices=Status.choices,
        default=Status.NO_RECORD,
    )

    version = models.PositiveIntegerField(
        "データ版",
        default=1,
    )

    created_at = models.DateTimeField(
        "作成日時",
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        "更新日時",
        auto_now=True,
    )

    class Meta:
        verbose_name = "勤務"
        verbose_name_plural = "勤務"
        ordering = ["-work_date"]

        constraints = [
            models.UniqueConstraint(
                fields=["employee", "work_date"],
                name="unique_employee_work_date",
            ),
            models.UniqueConstraint(
                fields=["employee"],
                condition=models.Q(
                    status__in=[
                        "working",
                        "on_break",
                    ]
                ),
                name="unique_active_session_per_employee",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.clock_in_at
            and self.work_date
            and timezone.localtime(
                self.clock_in_at
            ).date() != self.work_date
        ):
            raise ValidationError({
                "work_date": (
                    "勤務日は出勤日の日本日付にしてください。"
                )
            })

        if self.clock_out_at and not self.clock_in_at:
            raise ValidationError({
                "clock_out_at": (
                    "出勤日時が必要です。"
                )
            })

        if (
            self.clock_in_at
            and self.clock_out_at
            and self.clock_out_at <= self.clock_in_at
        ):
            raise ValidationError({
                "clock_out_at": (
                    "退勤日時は出勤日時より後にしてください。"
                )
            })

        if self.status == self.Status.NO_RECORD:
            if self.clock_in_at or self.clock_out_at:
                raise ValidationError(
                    "記録なしの勤務に打刻日時は設定できません。"
                )

        if self.status in (
            self.Status.WORKING,
            self.Status.ON_BREAK,
        ):
            if not self.clock_in_at or self.clock_out_at:
                raise ValidationError(
                    "勤務中・休憩中の日時が不正です。"
                )

        if self.status == self.Status.COMPLETED:
            if not self.clock_in_at or not self.clock_out_at:
                raise ValidationError(
                    "退勤済みには出退勤日時が必要です。"
                )

    def __str__(self):
        return (
            f"{self.employee.employee_number}"
            f" / {self.work_date}"
        )


class ClockEvent(models.Model):
    """変更しない原打刻イベント。"""

    class Kind(models.TextChoices):
        CLOCK_IN = "clock_in", "出勤"
        CLOCK_OUT = "clock_out", "退勤"
        BREAK_START = "break_start", "休憩開始"
        BREAK_END = "break_end", "休憩終了"

    work_session = models.ForeignKey(
        WorkSession,
        on_delete=models.PROTECT,
        related_name="clock_events",
        verbose_name="勤務",
    )

    kind = models.CharField(
        "打刻種別",
        max_length=20,
        choices=Kind.choices,
    )

    recorded_at = models.DateTimeField(
        "サーバー受信日時",
        default=timezone.now,
        editable=False,
    )

    operation_id = models.UUIDField(
        "操作ID",
        unique=True,
        editable=False,
    )

    class Meta:
        verbose_name = "原打刻"
        verbose_name_plural = "原打刻"
        ordering = ["recorded_at"]

    def __str__(self):
        return (
            f"{self.get_kind_display()}"
            f" / {self.recorded_at}"
        )


class BreakInterval(models.Model):
    """勤務に紐づく現在有効な休憩時間。"""

    work_session = models.ForeignKey(
        WorkSession,
        on_delete=models.PROTECT,
        related_name="break_intervals",
        verbose_name="勤務",
    )

    started_at = models.DateTimeField(
        "休憩開始日時",
    )

    ended_at = models.DateTimeField(
        "休憩終了日時",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "休憩"
        verbose_name_plural = "休憩"
        ordering = ["started_at"]

        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(ended_at__isnull=True)
                    | models.Q(
                        ended_at__gt=models.F("started_at")
                    )
                ),
                name="break_end_after_start",
            ),
            models.UniqueConstraint(
                fields=["work_session"],
                condition=models.Q(ended_at__isnull=True),
                name="unique_open_break_per_session",
            ),
        ]

    def clean(self):
        super().clean()

        if self.ended_at and self.ended_at <= self.started_at:
            raise ValidationError({
                "ended_at": (
                    "休憩終了は開始より後にしてください。"
                )
            })

    def __str__(self):
        return (
            f"{self.work_session.work_date}"
            f" / {self.started_at}"
        )


class MonthlyClosing(models.Model):
    """社員別の月次確定情報。"""

    class Status(models.TextChoices):
        OPEN = "open", "未確定"
        FINALIZED = "finalized", "確定済み"

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="monthly_closings",
        verbose_name="社員",
    )

    target_month = models.DateField(
        "対象月",
        help_text="対象月の1日を保存します。",
    )

    status = models.CharField(
        "確定状態",
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )

    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finalized_months",
        verbose_name="確定者",
    )

    finalized_at = models.DateTimeField(
        "確定日時",
        null=True,
        blank=True,
    )

    unlocked_at = models.DateTimeField(
        "最終確定解除日時",
        null=True,
        blank=True,
    )

    unlock_reason = models.CharField(
        "最終確定解除理由",
        max_length=500,
        blank=True,
    )

    version = models.PositiveIntegerField(
        "確定データ版",
        default=1,
    )

    class Meta:
        verbose_name = "月次確定"
        verbose_name_plural = "月次確定"
        ordering = ["-target_month"]

        constraints = [
            models.UniqueConstraint(
                fields=["employee", "target_month"],
                name="unique_employee_target_month",
            ),
        ]

    def clean(self):
        super().clean()

        if self.target_month and self.target_month.day != 1:
            raise ValidationError({
                "target_month": (
                    "対象月は月の1日を指定してください。"
                )
            })

        if (
            self.employee_id
            and self.finalized_by_id
            and self.employee_id == self.finalized_by_id
        ):
            raise ValidationError({
                "finalized_by": (
                    "自分の月次勤怠は確定できません。"
                )
            })

        if self.status == self.Status.FINALIZED:
            if not self.finalized_by_id or not self.finalized_at:
                raise ValidationError(
                    "確定者と確定日時が必要です。"
                )

    def __str__(self):
        return (
            f"{self.employee.employee_number}"
            f" / {self.target_month:%Y-%m}"
            f" / {self.get_status_display()}"
        )
