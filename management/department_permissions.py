from django.core.exceptions import PermissionDenied


def require_department_manager(request):
    """有効な業務管理者のみ部署管理を許可する。"""
    user = request.user

    if (
        not user.is_authenticated
        or not user.is_active
        or not getattr(user, "is_business_admin", False)
    ):
        raise PermissionDenied("部署管理機能を利用する権限がありません。")
