from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordChangeView,
)
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .forms import (
    EmployeeAuthenticationForm,
    EmployeePasswordChangeForm,
)


@method_decorator(never_cache, name="dispatch")
class EmployeeLoginView(LoginView):
    """社員用ログイン画面。期限切れ初期パスワードではログインさせない。"""

    template_name = "accounts/login.html"
    authentication_form = EmployeeAuthenticationForm

    def form_valid(self, form):
        user = form.get_user()
        expires_at = getattr(user, "initial_password_expires_at", None)
        if (
            user.must_change_password
            and expires_at is not None
            and timezone.now() >= expires_at
        ):
            form.add_error(
                None,
                "初期パスワードの有効期限が切れています。"
                "管理担当者へ再発行を依頼してください。",
            )
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self):
        user = self.request.user
        if user.is_authenticated and user.must_change_password:
            return reverse("accounts:password_change")
        return super().get_success_url()


@method_decorator(never_cache, name="dispatch")
class EmployeePasswordChangeView(PasswordChangeView):
    """本人によるパスワード変更。変更必須・期限を同時に解除する。"""

    template_name = "accounts/password_change.html"
    form_class = EmployeePasswordChangeForm
    success_url = reverse_lazy("attendance:home")

    def form_valid(self, form):
        with transaction.atomic():
            user = form.save()
            user.must_change_password = False
            user.initial_password_issued_at = None
            user.initial_password_expires_at = None
            user.save(update_fields=[
                "must_change_password",
                "initial_password_issued_at",
                "initial_password_expires_at",
            ])

        # パスワード変更後も本人の現在のセッションは維持する。
        update_session_auth_hash(self.request, user)
        messages.success(self.request, "パスワードを変更しました。")
        return HttpResponseRedirect(self.get_success_url())


class EmployeeLogoutView(LogoutView):
    """ログアウト処理。"""

    next_page = reverse_lazy("accounts:login")


@never_cache
@login_required
@require_GET
def account_overview(request):
    """社員本人のアカウント情報を表示する。"""
    employee = request.user
    department = getattr(employee, "department", None)
    department_label = str(department) if department else "未設定"
    is_business_admin = bool(
        getattr(employee, "is_business_admin", False)
    )
    account_role = (
        "管理者権限あり" if is_business_admin else "一般社員"
    )
    display_name = getattr(employee, "display_name", "")
    if not display_name:
        display_name = (
            employee.get_full_name() or employee.employee_number
        )

    context = {
        "employee_number": employee.employee_number,
        "display_name": display_name,
        "department_label": department_label,
        "account_role": account_role,
        "is_business_admin": is_business_admin,
        "account_active": employee.is_active,
    }
    return render(request, "accounts/overview.html", context)


@never_cache
@login_required
@require_GET
def usage_guide(request):
    """勤怠管理システムの使い方を表示する。"""
    return render(request, "accounts/guide.html")
