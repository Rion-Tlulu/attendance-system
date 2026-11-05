from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def business_admin_required(view_func):
    """業務管理者だけにアクセスを許可する"""

    @wraps(view_func)
    @login_required
    def wrapped(request, *args, **kwargs):

        user = request.user

        if not user.is_active or not getattr(user, "is_business_admin", False):
            raise PermissionDenied("この管理機能を利用する権限がありません")

        return view_func(request, *args, **kwargs)

    return wrapped
