from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
import uuid

from django.core.validators import MaxValueValidator, MinValueValidator


class EmploymentInfo(models.Model):
    """社員の所属・入退社情報"""

    employee = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="employement_info",
        verbose_name="社員",
    )

    department = models.CharField(
        "部署",
        max_length=100,
        blank=True,
    )

    hire_date = models.DateField(
        "入社日",
        null=True,
        blank=True,
    )

    leave_date = models.DateField(
        "退職日",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "雇用情報"
        verbose_name_plural = "雇用情報"

        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(hire_date__isnull=True)
                    | Q(leave_date__isnull=True)
                    | Q(leave_date__gte=F("hire_date"))
                ),
                name="employement_valid_dates",
            )
        ]

    def clean(self):
        super().clean()

        if self.hire_date and self.leave_date and self.leave_date < self.hire_date:
            raise ValidationError(
                {
                    "leave_date": "退職日は入社日以降にしてください",
                }
            )

    def __str__(self):
        return f"{self.employee.employee_number}/{self.department or '部署未設定'}"


class ExportBatch(models.Model):
    """A pair of CSVs tied to the same closing versions."""

    output_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    target_month = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    manifest = models.JSONField(default=list)


class Department(models.Model):
    """部署マスター。採番用コードは再利用しない。"""

    name = models.CharField(
        "部署名",
        max_length=100,
        unique=True,
    )
    code = models.PositiveSmallIntegerField(
        "採番用コード",
        unique=True,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(9),
        ],
    )
    is_active = models.BooleanField(
        "有効",
        default=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(code__gte=1) & Q(code__lte=9),
                name="department_code_1_to_9",
            ),
        ]

    def __str__(self):
        return f"{self.name}（コード{self.code}）"


class DepartmentRegistration(models.Model):
    """部署登録の操作IDと確定結果を保存する。"""

    department = models.OneToOneField(
        Department,
        on_delete=models.PROTECT,
        related_name="registration",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="department_registrations",
    )
    operation_id = models.UUIDField()
    name = models.CharField(max_length=100)
    code = models.PositiveSmallIntegerField()
    # 登録時の値を保持し、同じ操作IDで異なる内容の再送を拒否する。
    # 既存の登録履歴には値がないため null を許容する。
    is_active = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["actor", "operation_id"],
                name="unique_department_registration_operation",
            ),
            models.UniqueConstraint(
                fields=["code"],
                name="unique_department_registration_code",
            ),
        ]


class EmployeeNumberHistory(models.Model):
    """発行済み番号を永久に再利用しないための履歴。"""

    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="number_histories",
        null=True,
        blank=True,
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="number_histories",
    )
    employee_number = models.CharField(
        max_length=20,
        unique=True,
    )
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["issued_at", "pk"]


class EmployeeNumberOperation(models.Model):
    """社員登録・異動の再送に対する確定結果。"""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="employee_number_operations",
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="number_operations",
    )
    operation_id = models.UUIDField()
    kind = models.CharField(max_length=10)
    request_data = models.JSONField()
    issued_number = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["actor", "operation_id"],
                name="unique_employee_number_operation",
            ),
        ]
