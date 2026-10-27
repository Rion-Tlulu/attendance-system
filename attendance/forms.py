from django import forms

from .models import ClockEvent


class ClockActionForm(forms.Form):
    """出退勤・休憩打刻の送信フォーム。"""

    action = forms.ChoiceField(
        choices=ClockEvent.Kind.choices,
        widget=forms.HiddenInput,
    )

    operation_id = forms.UUIDField(
        widget=forms.HiddenInput,
    )
