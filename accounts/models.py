from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class EmployeeManager(BaseUserManager):
    """社員番号を使ってユーザーを作成する。"""

    use_in_migrations = True

    def create_user(self, employee_number, password=None, **extra_fields):
        if not employee_number:
            raise ValueError("社員番号は必須です。")
        if not password:
            raise ValueError("パスワードは必須です。")

        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("is_business_admin", False)

        user = self.model(employee_number=employee_number, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, employee_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_business_admin", False)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("is_staff=True が必要です。")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("is_superuser=True が必要です。")

        return self.create_user(employee_number, password, **extra_fields)


class Employee(AbstractUser):
    """勤怠管理システムの社員アカウント。"""

    username = None

    employee_number = models.CharField("社員番号", max_length=20, unique=True)
    department = models.CharField("部署", max_length=100, blank=True)
    hire_date = models.DateField("入社日", null=True, blank=True)
    retirement_date = models.DateField("退職日", null=True, blank=True)
    is_business_admin = models.BooleanField("業務管理者権限", default=False)
    must_change_password = models.BooleanField(
        "次回ログイン時にパスワード変更", default=False
    )
    # 旧社員の初期認証期限は移行時点では不明のため null を許容。
    initial_password_issued_at = models.DateTimeField(
        "初期パスワード発行日時", null=True, blank=True
    )
    initial_password_expires_at = models.DateTimeField(
        "初期パスワード有効期限", null=True, blank=True
    )

    USERNAME_FIELD = "employee_number"
    REQUIRED_FIELDS = []
    objects = EmployeeManager()

    class Meta:
        verbose_name = "社員"
        verbose_name_plural = "社員"
        ordering = ["employee_number"]

    @property
    def display_name(self):
        return f"{self.last_name} {self.first_name}".strip()

    def clean(self):
        super().clean()
        if (
            self.hire_date
            and self.retirement_date
            and self.retirement_date < self.hire_date
        ):
            raise ValidationError(
                {"retirement_date": "退職日は入社日以降にしてください。"}
            )

    def __str__(self):
        return f"{self.employee_number} - {self.display_name}"
