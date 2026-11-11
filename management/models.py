from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
import uuid


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
