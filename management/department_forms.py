from django import forms

from .department_rules import (
    available_department_codes,
    normalize_department_name,
)
from .models import Department


class DepartmentForm(forms.ModelForm):
    code = forms.TypedChoiceField(
        label="採番用コード",
        coerce=int,
        empty_value=None,
        required=True,
    )

    class Meta:
        model = Department
        fields = ["name", "code", "is_active"]
        labels = {
            "name": "部署名",
            "is_active": "有効な部署",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "maxlength": "100",
                    "autocomplete": "off",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            self.fields["code"].choices = [
                (
                    self.instance.code,
                    str(self.instance.code),
                )
            ]
            self.fields["code"].disabled = True
        else:
            self.fields["code"].choices = [
                (code, str(code)) for code in available_department_codes()
            ]
            self.fields["is_active"].widget = forms.HiddenInput()
            self.fields["is_active"].initial = True

    def clean_name(self):
        name = normalize_department_name(self.cleaned_data["name"])

        queryset = Department.objects.filter(name=name)

        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists() or any(
            existing.strip() == name
            for existing in Department.objects.exclude(pk=self.instance.pk).values_list("name", flat=True)
        ):
            raise forms.ValidationError("この部署名は既に登録されています。")

        return name

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk and not cleaned.get("is_active"):
            self.add_error("is_active", "新しい部署は有効な状態で登録してください。")
        if self.instance.pk and "code" in self.data:
            # disabled フィールドは Django が POST 値を無視するため、明示的に検査する。
            if str(self.data["code"]) != str(self.instance.code):
                self.add_error("code", "部署コードは変更できません。")
        return cleaned
