from django import forms
from django.forms import formset_factory

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

# 画面 07：対象ごとの操作。未送信（空）の場合は従来どおり入力された日時をそのまま使う。
OPERATION_CHOICES = [
    ("keep", "変更しない"),
    ("add", "追加"),
    ("change", "変更"),
    ("cancel", "取消"),
]


class CorrectionValuesForm(forms.Form):
    """修正後の勤務全体と理由を入力する"""

    clock_in_at = forms.DateTimeField(
        label="出勤日時",
        required=False,
        input_formats=[
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
        ],
        widget=forms.DateTimeInput(
            format=DATETIME_FORMAT,
            attrs={
                "type": "datetime-local",
                "step": "1",
            },
        ),
    )

    clock_out_at = forms.DateTimeField(
        label="退勤日時",
        required=False,
        input_formats=[
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
        ],
        widget=forms.DateTimeInput(
            format=DATETIME_FORMAT,
            attrs={
                "type": "datetime-local",
                "step": "1",
            },
        ),
    )

    clock_in_op = forms.ChoiceField(
        label="出勤の操作",
        choices=OPERATION_CHOICES,
        required=False,
        widget=forms.RadioSelect,
    )

    clock_out_op = forms.ChoiceField(
        label="退勤の操作",
        choices=OPERATION_CHOICES,
        required=False,
        widget=forms.RadioSelect,
    )

    reason = forms.CharField(
        label="修正申請の理由",
        max_length=500,
        strip=True,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "maxlength": 500,
                "placeholder": ("修正が必要な理由を入力してください"),
            },
        ),
    )

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()

        if not reason:
            raise forms.ValidationError("申請理由を入力してください")

        return reason

    def clean(self):
        cleaned_data = super().clean()

        for name, label in (("clock_in", "出勤"), ("clock_out", "退勤")):
            operation = cleaned_data.get(f"{name}_op") or ""
            field = f"{name}_at"

            if operation == "cancel":
                # 取消は有効値を空にする申請として扱う（07章）。
                cleaned_data[field] = None
            elif (
                operation in ("add", "change")
                and cleaned_data.get(field) is None
                and field not in self.errors
            ):
                self.add_error(field, f"{label}の変更後の日時を入力してください。")

        return cleaned_data


class CorrectionBreakForm(forms.Form):
    """修正案に含める休憩1件分"""

    started_at = forms.DateTimeField(
        label="休憩開始",
        required=False,
        input_formats=[
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
        ],
        widget=forms.DateTimeInput(
            format=DATETIME_FORMAT,
            attrs={
                "type": "datetime-local",
                "step": "1",
            },
        ),
    )

    ended_at = forms.DateTimeField(
        label="休憩終了",
        required=False,
        input_formats=[
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
        ],
        widget=forms.DateTimeInput(
            format=DATETIME_FORMAT,
            attrs={
                "type": "datetime-local",
                "step": "1",
            },
        ),
    )

    op = forms.ChoiceField(
        label="休憩の操作",
        choices=OPERATION_CHOICES,
        required=False,
        widget=forms.HiddenInput,
    )

    def clean(self):
        cleaned_data = super().clean()
        operation = cleaned_data.get("op") or ""

        if operation == "cancel":
            # 取消した休憩は修正案に含めない。
            cleaned_data["DELETE"] = True
            return cleaned_data

        start = cleaned_data.get("started_at")
        end = cleaned_data.get("ended_at")

        if operation in ("add", "change") and not start and not end:
            raise forms.ValidationError("休憩の開始と終了を入力してください。")

        if bool(start) != bool(end):
            raise forms.ValidationError("休憩の開始と終了は両方入力してください。")

        return cleaned_data


CorrectionBreakFormSet = formset_factory(
    CorrectionBreakForm,
    extra=0,
    can_delete=True,
    max_num=20,
    validate_max=True,
    absolute_max=25,
)
