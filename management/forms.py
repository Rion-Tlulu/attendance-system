"""管理者用フォーム。"""

from django import forms
from django.contrib.auth import get_user_model

from .models import EmploymentInfo

Employee = get_user_model()


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
        widget=forms.Textarea(attrs={"rows": 4, "maxlength": 500}),
    )

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get("action")
        return_reason = (cleaned_data.get("return_reason") or "").strip()
        if action == "return" and not return_reason:
            self.add_error("return_reason", "差戻し理由を入力してください。")
        cleaned_data["return_reason"] = return_reason
        return cleaned_data


class MonthClosingForm(forms.Form):
    """記録なしの日の照合確認。"""

    checked_no_record = forms.BooleanField(
        label="別管理資料との照合を確認した",
        required=True,
    )


employee_field_names = {field.name for field in Employee._meta.fields}
profile_fields = [
    name
    for name in ("first_name", "last_name", "department")
    if name in employee_field_names
]


class EmployeeCreateForm(forms.ModelForm):
    """社員登録。初期パスワードはサーバー側で生成する。"""

    hire_date = forms.DateField(
        label="入社日",
        required=True,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    class Meta:
        model = Employee
        fields = ["employee_number", *profile_fields]


class EmployeeEditForm(forms.ModelForm):
    """社員の基本情報を編集するフォーム。"""

    change_reason = forms.CharField(
        label="変更理由",
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = Employee
        fields = ["employee_number", *profile_fields, "is_active"]

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and (
            cleaned.get("employee_number") != self.instance.employee_number
            or cleaned.get("is_active") != self.instance.is_active
        ) and not (cleaned.get("change_reason") or "").strip():
            self.add_error("change_reason", "社員番号・利用状態の変更理由を入力してください。")
        return cleaned


class EmploymentInfoForm(forms.ModelForm):
    """社員の部署・入退社日を編集する。"""

    hire_date = forms.DateField(
        label="入社日",
        required=True,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    change_reason = forms.CharField(
        label="変更理由",
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = EmploymentInfo
        fields = ["department", "hire_date", "leave_date"]
        widgets = {
            "department": forms.TextInput(attrs={"maxlength": 100}),
            "hire_date": forms.DateInput(attrs={"type": "date"}),
            "leave_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and (
            cleaned.get("hire_date") != self.instance.hire_date
            or cleaned.get("leave_date") != self.instance.leave_date
        ) and not (cleaned.get("change_reason") or "").strip():
            self.add_error("change_reason", "在籍日の変更理由を入力してください。")
        return cleaned
