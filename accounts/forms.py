
from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
)


class EmployeeAuthenticationForm(AuthenticationForm):
    """社員番号によるログインフォーム。"""

    username = forms.CharField(
        label="社員番号",
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "username",
                "inputmode": "text",
                "placeholder": "例：00124",
                "autofocus": True,
            }
        ),
    )

    password = forms.CharField(
        label="パスワード",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
                "placeholder": "パスワードを入力",
            }
        ),
    )


class EmployeePasswordChangeForm(PasswordChangeForm):
    """本人によるパスワード変更フォーム。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["old_password"].label = (
            "現在のパスワード"
        )
        self.fields["new_password1"].label = (
            "新しいパスワード"
        )
        self.fields["new_password2"].label = (
            "新しいパスワード（確認）"
        )

        self.fields["old_password"].widget.attrs.update({
            "autocomplete": "current-password",
        })

        self.fields["new_password1"].widget.attrs.update({
            "autocomplete": "new-password",
        })

        self.fields["new_password2"].widget.attrs.update({
            "autocomplete": "new-password",
        })
