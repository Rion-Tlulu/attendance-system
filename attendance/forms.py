from django import forms

from .models import ClockEvent

import re
from datetime import date


class ClockActionForm(forms.Form):
    """出退勤・休憩打刻の送信フォーム。"""

    action = forms.ChoiceField(
        choices=ClockEvent.Kind.choices,
        widget=forms.HiddenInput,
    )

    operation_id = forms.UUIDField(
        widget=forms.HiddenInput,
    )


class MonthSelectForm(forms.Form):
    """年月選択フォーム。"""

    month = forms.CharField(
        label="対象月",
        max_length=7,
        widget=forms.TextInput(
            attrs={
                "type": "month",
                "class": "month-input",
                "autocomplete": "off",
            }
        ),
    )

    def clean_month(self):
        value = self.cleaned_data["month"]

        if not re.fullmatch(
            r"[0-9]{4}-(0[1-9]|1[0-2])",
            value,
        ):
            raise forms.ValidationError("年月はYYYY-MM形式で入力してください。")

        try:
            return date.fromisoformat(f"{value}-01")
        except ValueError as exc:
            raise forms.ValidationError("正しい年月を指定してください。") from exc
