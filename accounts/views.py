
from django.contrib import messages
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordChangeView,
)
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from .forms import (
    EmployeeAuthenticationForm,
    EmployeePasswordChangeForm,
)


@method_decorator(never_cache, name="dispatch")
class EmployeeLoginView(LoginView):
    """社員用ログイン画面。"""

    template_name = "accounts/login.html"
    authentication_form = EmployeeAuthenticationForm

    def get_success_url(self):
        user = self.request.user

        if (
            user.is_authenticated
            and user.must_change_password
        ):
            return reverse(
                "accounts:password_change"
            )

        return super().get_success_url()


@method_decorator(never_cache, name="dispatch")
class EmployeePasswordChangeView(PasswordChangeView):
    """本人によるパスワード変更画面。"""

    template_name = "accounts/password_change.html"
    form_class = EmployeePasswordChangeForm
    success_url = reverse_lazy("attendance:home")

    def form_valid(self, form):
        response = super().form_valid(form)

        user = self.request.user

        if user.must_change_password:
            user.must_change_password = False
            user.save(
                update_fields=["must_change_password"]
            )

        messages.success(
            self.request,
            "パスワードを変更しました。",
        )

        return response


class EmployeeLogoutView(LogoutView):
    """ログアウト処理。"""

    next_page = reverse_lazy("accounts:login")
