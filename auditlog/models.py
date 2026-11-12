from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditLog(models.Model):
    """
    勤怠管理システムの業務操作に関する監査履歴。

    打刻、修正申請、承認・差戻し、
    月次確定、社員管理、CSV出力などを記録する。
    """

    # ==========================================
    # 操作種別
    # ==========================================

    class Action(models.TextChoices):

        # --------------------------------------
        # 打刻操作
        # --------------------------------------

        CLOCK = (
            "clock",
            "打刻",
        )

        # --------------------------------------
        # 修正申請
        # --------------------------------------

        CORRECTION_SUBMIT = (
            "correction_submit",
            "修正申請の提出",
        )

        CORRECTION_WITHDRAW = (
            "correction_withdraw",
            "修正申請の取下げ",
        )

        CORRECTION_APPROVE = (
            "correction_approve",
            "修正申請の承認",
        )

        CORRECTION_RETURN = (
            "correction_return",
            "修正申請の差戻し",
        )

        # --------------------------------------
        # 月次勤怠
        # --------------------------------------

        MONTH_FINALIZE = (
            "month_finalize",
            "月次確定",
        )

        # 以前の実装との互換性のため保持
        MONTH_UNLOCK = (
            "month_unlock",
            "月次確定解除",
        )

        # Phase 9の確定解除処理で使用
        MONTH_REOPEN = (
            "month_reopen",
            "月次勤怠の確定解除",
        )

        # --------------------------------------
        # 社員管理
        # --------------------------------------

        EMPLOYEE_CREATE = (
            "employee_create",
            "社員の登録",
        )

        EMPLOYEE_UPDATE = (
            "employee_update",
            "社員情報変更",
        )

        EMPLOYEE_DISABLE = (
            "employee_disable",
            "社員利用無効化",
        )

        ROLE_CHANGE = (
            "role_change",
            "権限変更",
        )

        DEPARTMENT_CREATE = ("department_create", "部署の登録")
        DEPARTMENT_UPDATE = ("department_update", "部署情報変更")

        # --------------------------------------
        # CSV出力
        # --------------------------------------

        CSV_EXPORT = (
            "csv_export",
            "CSV出力",
        )

        # --------------------------------------
        # 認証
        # --------------------------------------

        AUTH_FAILURE = (
            "auth_failure",
            "認証失敗",
        )

    # ==========================================
    # 操作実行者
    # ==========================================

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="performed_audits",
        verbose_name="実行者",
    )

    # ==========================================
    # 操作対象社員
    # ==========================================

    target_employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="targeted_audits",
        verbose_name="対象社員",
    )

    # ==========================================
    # 操作種別
    # ==========================================

    action = models.CharField(
        "操作種別",
        max_length=40,
        choices=Action.choices,
    )

    # ==========================================
    # 操作対象
    # ==========================================

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

    # ==========================================
    # 変更前・変更後の情報
    # ==========================================

    before_data = models.JSONField(
        "変更前",
        default=dict,
    )

    after_data = models.JSONField(
        "変更後",
        default=dict,
    )

    # ==========================================
    # 操作理由
    # ==========================================

    reason = models.TextField(
        "理由",
        blank=True,
    )

    # ==========================================
    # 補足情報
    # ==========================================

    details = models.JSONField(
        "補足情報",
        default=dict,
    )

    # ==========================================
    # 操作日時
    # ==========================================

    occurred_at = models.DateTimeField(
        "実行日時",
        default=timezone.now,
        editable=False,
    )

    # ==========================================
    # モデル設定
    # ==========================================

    class Meta:
        verbose_name = "操作履歴"
        verbose_name_plural = "操作履歴"

        # 新しい操作から表示
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

    # ==========================================
    # 文字列表現
    # ==========================================

    def __str__(self):
        return f"{self.get_action_display()}" f" / {self.occurred_at}"
