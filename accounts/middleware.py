"""初期パスワード利用中の社員を業務画面・APIから遮断する。"""

from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin


class InitialPasswordRequiredMiddleware(MiddlewareMixin):
    """認証後でも初回変更まではパスワード変更・ログアウト以外拒否。"""

    ALLOWED_VIEWS = frozenset(
        {
            "accounts:password_change",
            "accounts:logout",
        }
    )

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if (
            user is None
            or not user.is_authenticated
            or not getattr(user, "must_change_password", False)
        ):
            return None

        expires_at = getattr(user, "initial_password_expires_at", None)
        if expires_at is not None and timezone.now() >= expires_at:
            logout(request)
            messages.error(
                request,
                "初期パスワードの期限が切れています。"
                "管理担当者へ再発行を依頼してください。",
            )
            return redirect("accounts:login")

        match = getattr(request, "resolver_match", None)
        view_name = match.view_name if match is not None else None
        if view_name in self.ALLOWED_VIEWS:
            return None

        if request.method not in ("GET", "HEAD"):
            if "application/json" in request.headers.get("Accept", ""):
                return JsonResponse(
                    {"detail": "初回パスワード変更が必要です。"},
                    status=403,
                )
            return HttpResponseForbidden("初回パスワード変更が必要です。")

        return redirect("accounts:password_change")
