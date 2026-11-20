"""左メニュー（21章 階層メニュー）の現在地を判定するテンプレートタグ。"""

from django import template
from django.urls import reverse

register = template.Library()

# (グループ見出し, アイコン, [(リンク名, URL名, 現在地とみなすビュー名の集合)])
MANAGEMENT_MENU = [
    ("勤怠管理", "fa-regular fa-calendar", [
        ("勤怠一覧", "management:attendance_list", {"management:attendance_list", "management:home"}),
        ("申請一覧", "management:corrections", {"management:corrections", "management:correction_detail"}),
    ]),
    ("月次管理", "fa-solid fa-chart-simple", [
        ("月次詳細と出力", "management:attendance_list", {
            "management:employee_month", "management:bulk_export",
            "management:batch_detail", "management:proxy_correction",
        }),
    ]),
    ("社員・権限管理", "fa-regular fa-user", [
        ("社員管理", "management:employees", {
            "management:employees", "management:employee_create", "management:employee_edit",
            "management:employment_edit", "management:employee_password_reset",
        }),
        ("部署登録", "management:department_list", {
            "management:department_list", "management:department_create",
            "management:department_edit", "management:department_registration_result",
        }),
        ("業務管理者の権限管理", "management:role_list", {"management:role_list", "management:employee_role"}),
    ]),
    ("運用メニュー", "fa-solid fa-gear", [
        ("操作履歴", "management:audit_history", {"management:audit_history", "management:audit_detail"}),
        ("アカウントと使い方", "accounts:overview", set()),
    ]),
]

EMPLOYEE_MENU = [
    ("打刻メニュー", "fa-regular fa-clock", [
        ("打刻ホーム", "attendance:home", {"attendance:home"}),
    ]),
    ("勤怠メニュー", "fa-regular fa-calendar", [
        ("自分の勤怠", "attendance:monthly", {"attendance:monthly", "attendance:daily", "corrections:*"}),
    ]),
    ("アカウントメニュー", "fa-regular fa-user", [
        ("アカウントと使い方", "accounts:overview", {"accounts:*"}),
    ]),
]


def _matches(view_name, namespace, patterns):
    return view_name in patterns or f"{namespace}:*" in patterns


@register.simple_tag(takes_context=True)
def side_menu(context):
    """表示中の役割のメニューと、現在地・開いた中項目を返す。"""
    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    view_name = getattr(match, "view_name", "") or ""
    namespace = getattr(match, "namespace", "") or ""
    is_management = namespace == "management"
    groups = []
    for index, (label, icon, links) in enumerate(MANAGEMENT_MENU if is_management else EMPLOYEE_MENU):
        items = []
        for link_label, url_name, patterns in links:
            items.append({
                "label": link_label,
                "url": reverse(url_name),
                "current": _matches(view_name, namespace, patterns),
            })
        groups.append({
            "id": f"side-group-{index}",
            "label": label,
            "icon": icon,
            "items": items,
            "open": any(item["current"] for item in items),
        })
    return {
        "title": "管理者メニュー" if is_management else "社員メニュー",
        "groups": groups,
    }
