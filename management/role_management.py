"""業務管理者権限の変更と人数制約。"""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from accounts.audit_context import current_actor


class RoleChangeError(Exception):
    """画面に表示できる権限変更の業務エラー。"""


@transaction.atomic
def change_business_admin_role(*, actor_id, employee_id, grant, expected_role, reason):
    """現行の権限を再確認し、変更と監査記録を同一トランザクションで保存する。"""

    Employee = get_user_model()
    reason = reason.strip()
    if not 1 <= len(reason) <= 500:
        raise RoleChangeError("変更理由を1〜500文字で入力してください。")

    # すべての権限変更で同じ順序にロックし、同時の権限取消を直列化する。
    active_admin_ids = list(Employee.objects.select_for_update().filter(
        is_active=True, is_business_admin=True,
    ).order_by("pk").values_list("pk", flat=True))
    actor = Employee.objects.select_for_update().get(pk=actor_id)
    if not actor.is_active or not actor.is_business_admin:
        raise PermissionDenied("この管理機能を利用する権限がありません。")

    target = Employee.objects.select_for_update().get(pk=employee_id)
    if target.is_staff or target.is_superuser:
        raise RoleChangeError("技術管理用アカウントの業務権限はこの画面から変更できません。")
    if target.is_business_admin != expected_role:
        raise RoleChangeError("権限が別の操作で変更されました。画面を再読み込みしてください。")
    if target.is_business_admin == grant:
        raise RoleChangeError("権限はすでに選択された状態です。")
    if grant and not target.is_active:
        raise RoleChangeError("利用停止中の社員には権限を付与できません。先に利用を再開してください。")
    if not grant and target.pk == actor.pk:
        raise RoleChangeError("自分自身の業務管理者権限は取り消せません。")
    if not grant and target.pk in active_admin_ids and len(active_admin_ids) <= 2:
        raise RoleChangeError("有効な業務管理者は2人以上必要です。後任を先に登録してください。")

    target.is_business_admin = grant
    target._role_change_reason = reason
    token = current_actor.set(actor)
    try:
        target.save(update_fields=["is_business_admin"])
    except ValidationError as exc:
        raise RoleChangeError(" ".join(exc.messages)) from exc
    finally:
        current_actor.reset(token)
    return target
