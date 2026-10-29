from django import forms
from django.forms import formset_factory

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


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

    def clean(self):
        cleaned_data = super().clean()

        start = cleaned_data.get("started_at")
        end = cleaned_data.get("ended_at")

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
