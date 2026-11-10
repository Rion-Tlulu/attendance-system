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

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET


@method_decorator(never_cache, name="dispatch")
class EmployeeLoginView(LoginView):
    """社員用ログイン画面。"""

    template_name = "accounts/login.html"
    authentication_form = EmployeeAuthenticationForm

    def get_success_url(self):
        user = self.request.user

        if user.is_authenticated and user.must_change_password:
            return reverse("accounts:password_change")

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
            user.save(update_fields=["must_change_password"])

        messages.success(
            self.request,
            "パスワードを変更しました。",
        )

        return response


class EmployeeLogoutView(LogoutView):
    """ログアウト処理。"""

    next_page = reverse_lazy("accounts:login")


# Phase 8 ：アカウントと使い方


@never_cache
@login_required
@require_GET
def account_overview(request):
    """社員本人のアカウント情報を表示する"""

    employee = request.user

    # 所属部署は既存モデルの値を参照
    department = getattr(
        employee,
        "department",
        None,
    )

    department_label = str(department) if department else "未設定"

    # Django管理サイト権限（is_staff）とは区別する
    is_business_admin = bool(
        getattr(
            employee,
            "is_business_admin",
            False,
        )
    )

    account_role = "管理者権限あり" if is_business_admin else "一般社員"

    display_name = getattr(
        employee,
        "display_name",
        "",
    )

    if not display_name:
        display_name = employee.get_full_name() or employee.employee_number

    context = {
        "employee_number": employee.employee_number,
        "display_name": display_name,
        "department_label": department_label,
        "account_role": account_role,
        "is_business_admin": is_business_admin,
        "account_active": employee.is_active,
    }

    return render(
        request,
        "accounts/overview.html",
        context,
    )


@never_cache
@login_required
@require_GET
def usage_guide(request):
    """勤怠管理システムの使い方を表示する"""

    return render(
        request,
        "accounts/guide.html",
    )
