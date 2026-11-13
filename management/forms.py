"""管理者用フォーム。"""

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from .department_rules import (
    available_department_codes,
    normalize_department_name,
)
from .models import Department, EmploymentInfo

Employee = get_user_model()


# ============================================================
# 承認・差戻しフォーム
# ============================================================


class ReviewForm(forms.Form):
    """承認・差戻しの入力フォーム。"""

    action = forms.ChoiceField(
        label="審査結果",
        choices=[
            ("approve", "承認する"),
            ("return", "差し戻す"),
        ],
        widget=forms.RadioSelect,
    )

    return_reason = forms.CharField(
        label="差戻し理由",
        max_length=500,
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "maxlength": 500,
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()

        action = cleaned_data.get("action")
        return_reason = (cleaned_data.get("return_reason") or "").strip()

        if action == "return" and not return_reason:
            self.add_error(
                "return_reason",
                "差戻し理由を入力してください。",
            )

        cleaned_data["return_reason"] = return_reason

        return cleaned_data


# ============================================================
# 月次締めフォーム
# ============================================================


class MonthClosingForm(forms.Form):
    """記録なしの日の照合確認。"""

    checked_no_record = forms.BooleanField(
        label="別管理資料との照合を確認した",
        required=True,
    )
    reconciliation_token = forms.CharField(required=False, widget=forms.HiddenInput)


# ============================================================
# 社員モデルのフィールド確認
# ============================================================

employee_field_names = {field.name for field in Employee._meta.fields}

profile_fields = [
    name
    for name in (
        "first_name",
        "last_name",
        "department",
    )
    if name in employee_field_names
]


# ============================================================
# 部署選択共通処理
# ============================================================


class DepartmentSelectionMixin:
    """社員登録・編集画面の部署選択機能。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        department_field = forms.ModelChoiceField(
            queryset=Department.objects.none(),
            label="所属部署",
            required=True,
            empty_label="部署を選択してください",
        )

        self.fields["department_choice"] = department_field

        queryset = Department.objects.filter(is_active=True)

        # 編集時は現在の部署が停止中でも表示する。
        if self.instance.pk and self.instance.department:
            queryset = Department.objects.filter(
                Q(is_active=True) | Q(name=self.instance.department)
            )

            current = Department.objects.filter(name=self.instance.department).first()

            if current:
                department_field.initial = current.pk

        department_field.queryset = queryset.order_by("code")

    def clean_department_choice(self):
        department = self.cleaned_data.get("department_choice")

        if department is None:
            return department

        if not department.is_active:
            if self.instance.pk and self.instance.department == department.name:
                return department

            raise forms.ValidationError("停止中の部署は選択できません。")

        return department

    def clean(self):
        cleaned = super().clean()

        # 動的に追加したフィールドを検証する。
        department = cleaned.get("department_choice")

        if department is not None:
            if not department.is_active:
                if not (
                    self.instance.pk and self.instance.department == department.name
                ):
                    self.add_error(
                        "department_choice",
                        "停止中の部署は選択できません。",
                    )

        return cleaned

    def save(self, commit=True):
        employee = super().save(commit=False)

        department = self.cleaned_data.get("department_choice")

        if department is not None:
            employee.department = department.name

        if commit:
            employee.save()
            self.save_m2m()

        return employee


# ============================================================
# 社員新規登録フォーム
# ============================================================


class EmployeeCreateForm(
    DepartmentSelectionMixin,
    forms.ModelForm,
):
    """社員登録フォーム。"""

    first_name = forms.CharField(label="名", max_length=150, required=True)
    last_name = forms.CharField(label="姓", max_length=150, required=True)

    hire_date = forms.DateField(
        label="入社日",
        required=True,
        widget=forms.DateInput(
            attrs={
                "type": "date",
            }
        ),
    )

    class Meta:
        model = Employee

        # department_choice はフォーム専用フィールド。
        # Employeeモデルには存在しないため指定しない。
        fields = [
            "first_name",
            "last_name",
        ]


# ============================================================
# 社員編集フォーム
# ============================================================


class EmployeeEditForm(
    DepartmentSelectionMixin,
    forms.ModelForm,
):
    """社員編集フォーム。"""

    first_name = forms.CharField(label="名", max_length=150, required=True)
    last_name = forms.CharField(label="姓", max_length=150, required=True)

    change_reason = forms.CharField(
        label="変更理由",
        max_length=500,
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "maxlength": 500,
            }
        ),
    )

    class Meta:
        model = Employee

        fields = [
            "first_name",
            "last_name",
            "is_active",
        ]

    def clean(self):
        cleaned = super().clean()

        if not self.instance.pk:
            return cleaned

        status_changed = cleaned.get("is_active") != self.instance.is_active

        selected = cleaned.get("department_choice")

        department_changed = (
            selected is not None and selected.name != self.instance.department
        )
        name_changed = (
            cleaned.get("first_name") != self.instance.first_name
            or cleaned.get("last_name") != self.instance.last_name
        )

        reason = (cleaned.get("change_reason") or "").strip()

        if (status_changed or department_changed or name_changed) and not reason:
            self.add_error(
                "change_reason",
                "変更理由を入力してください。",
            )

        return cleaned


# ============================================================
# 業務管理者権限変更フォーム
# ============================================================


class BusinessAdminRoleForm(forms.Form):
    """業務管理者権限だけを変更する確認フォーム。"""

    expected_role = forms.ChoiceField(
        choices=[
            ("employee", "一般社員"),
            ("admin", "業務管理者"),
        ],
        widget=forms.HiddenInput,
    )

    desired_role = forms.ChoiceField(
        label="変更後の権限",
        choices=[
            ("employee", "一般社員"),
            ("admin", "業務管理者"),
        ],
        widget=forms.RadioSelect,
    )

    change_reason = forms.CharField(
        label="変更理由",
        max_length=500,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "maxlength": 500,
            }
        ),
    )

    def clean_change_reason(self):
        reason = self.cleaned_data["change_reason"].strip()

        if not reason:
            raise forms.ValidationError("変更理由を入力してください。")

        return reason


# ============================================================
# 雇用情報編集フォーム
# ============================================================


class EmploymentInfoForm(forms.ModelForm):
    """社員の部署・入退社日を編集する。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].disabled = True
        self.fields["department"].help_text = "部署異動は社員情報の編集画面から行ってください。"

    hire_date = forms.DateField(
        label="入社日",
        required=True,
        widget=forms.DateInput(
            attrs={
                "type": "date",
            }
        ),
    )

    change_reason = forms.CharField(
        label="変更理由",
        max_length=500,
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "maxlength": 500,
            }
        ),
    )

    class Meta:
        model = EmploymentInfo

        fields = [
            "department",
            "hire_date",
            "leave_date",
        ]

        widgets = {
            "department": forms.TextInput(
                attrs={
                    "maxlength": 100,
                }
            ),
            "hire_date": forms.DateInput(
                attrs={
                    "type": "date",
                }
            ),
            "leave_date": forms.DateInput(
                attrs={
                    "type": "date",
                }
            ),
        }

    def clean(self):
        cleaned = super().clean()

        if "department" in self.data and self.data.get("department", "") != self.instance.department:
            self.add_error("department", "部署異動は社員情報の編集画面で登録済みの部署を選択してください。")

        if (
            self.instance.pk
            and (
                cleaned.get("hire_date") != self.instance.hire_date
                or cleaned.get("leave_date") != self.instance.leave_date
            )
            and not (cleaned.get("change_reason") or "").strip()
        ):
            self.add_error(
                "change_reason",
                "在籍日の変更理由を入力してください。",
            )

        return cleaned


# ============================================================
# 部署新規登録フォーム
# ============================================================


class DepartmentCreateForm(forms.Form):
    """部署マスターの新規登録フォーム。"""

    name = forms.CharField(
        label="部署名",
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
            }
        ),
    )

    code = forms.TypedChoiceField(
        label="採番用コード",
        coerce=int,
        empty_value=None,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["code"].choices = [
            (code, str(code)) for code in available_department_codes()
        ]

    def clean_name(self):
        return normalize_department_name(self.cleaned_data["name"])
