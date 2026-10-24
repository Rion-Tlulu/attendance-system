
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def business_admin_required(view_func):
    """業務管理者のみアクセス可能にする。"""

    @login_required
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        user = request.user

        if not user.is_active or not user.is_business_admin:
            raise PermissionDenied(
                "この画面を利用する権限がありません。"
            )

        return view_func(request, *args, **kwargs)

    return wrapped_view
