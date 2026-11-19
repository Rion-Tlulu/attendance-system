"""A05 読み取り専用の監査ログ一覧データ。"""

from datetime import datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django import template
from django.core.paginator import Paginator
from django.db.models import Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from auditlog.models import AuditLog

register = template.Library()
JST = ZoneInfo("Asia/Tokyo")


def _detail_url(pk):
    """既存の監査詳細画面へのURL。"""
    for name in (
        "management:audit_detail",
        "management:audit_log_detail",
    ):
        try:
            return reverse(name, args=[pk])
        except NoReverseMatch:
            pass

    return ""


def _page_query(filters, page):
    return urlencode(
        {
            **filters,
            "page": page,
        }
    )


@register.simple_tag(takes_context=True)
def a05_audit(context):
    """管理者だけに監査ログを返す。"""

    request = context.get("request")
    user = getattr(request, "user", None)

    if (
        not user
        or not user.is_authenticated
        or not user.is_active
        or not getattr(user, "is_business_admin", False)
    ):
        return {"allowed": False}

    today = timezone.localdate()

    filters = {
        "from_date": (
            request.GET.get("from_date") or (today - timedelta(days=30)).isoformat()
        ).strip()[:10],
        "to_date": (request.GET.get("to_date") or today.isoformat()).strip()[:10],
        "action": (request.GET.get("action") or "").strip()[:80],
        "q": (request.GET.get("q") or "").strip()[:100],
    }

    errors = []

    try:
        date_from = parse_date(filters["from_date"])
        date_to = parse_date(filters["to_date"])
    except ValueError:
        date_from = date_to = None

    if not date_from or not date_to:
        errors.append("開始日と終了日は正しい日付を指定してください。")

    elif date_from > date_to:
        errors.append("開始日は終了日以前にしてください。")

    elif date_to.year == 9999:
        errors.append("終了日の年は9998年以前を指定してください。")

    action_choices = list(AuditLog._meta.get_field("action").choices or [])

    valid_actions = {str(value) for value, _ in action_choices}

    if filters["action"] and filters["action"] not in valid_actions:
        errors.append("操作種別を確認してください。")

    queryset = AuditLog.objects.all()

    field_names = {field.name for field in AuditLog._meta.get_fields()}

    relations = [name for name in ("actor", "target_employee") if name in field_names]

    if relations:
        queryset = queryset.select_related(*relations)

    if errors:
        queryset = queryset.none()

    else:
        start = datetime.combine(
            date_from,
            time.min,
            tzinfo=JST,
        )

        end = datetime.combine(
            date_to + timedelta(days=1),
            time.min,
            tzinfo=JST,
        )

        queryset = queryset.filter(
            occurred_at__gte=start,
            occurred_at__lt=end,
        )

        if filters["action"]:
            queryset = queryset.filter(action=filters["action"])

        if filters["q"]:
            clauses = Q()

            if "actor" in field_names:
                clauses |= Q(actor__employee_number__icontains=filters["q"])

            if "target_employee" in field_names:
                clauses |= Q(target_employee__employee_number__icontains=filters["q"])

            queryset = queryset.filter(clauses) if clauses else queryset.none()

    queryset = queryset.order_by(
        "-occurred_at",
        "-pk",
    )

    paginator = Paginator(queryset, 25)

    page_obj = paginator.get_page(request.GET.get("page"))

    rows = []

    for log in page_obj.object_list:

        actor = getattr(log, "actor", None)
        target = getattr(log, "target_employee", None)

        action_label = (
            log.get_action_display()
            if hasattr(log, "get_action_display")
            else str(log.action)
        )

        rows.append(
            {
                "id": log.pk,
                "occurred_at": log.occurred_at,
                "action_label": action_label,
                "actor_number": (getattr(actor, "employee_number", "") or "システム"),
                "actor_name": getattr(actor, "display_name", "") or "システム",
                "target_number": (getattr(target, "employee_number", "") or "—"),
                "target_name": getattr(target, "display_name", "") or (log.after_data or {}).get("name", "") or log.target_model,
                "reason": (getattr(log, "reason", "") or ""),
                "detail_url": "?" + urlencode({**filters, "page": page_obj.number, "selected": log.pk}) + "#audit-selected",
            }
        )

    selected = next((log for log in page_obj if str(log.pk) == request.GET.get("selected")), None)
    if selected is None:
        selected = next(iter(page_obj), None)
    return {
        "allowed": True,
        "filters": filters,
        "errors": errors,
        "action_choices": action_choices,
        "total_count": paginator.count,
        "page_obj": page_obj,
        "rows": rows,
        "selected_log": selected,
        "previous_query": (
            _page_query(
                filters,
                page_obj.previous_page_number(),
            )
            if page_obj.has_previous()
            else ""
        ),
        "next_query": (
            _page_query(
                filters,
                page_obj.next_page_number(),
            )
            if page_obj.has_next()
            else ""
        ),
    }


# ------------------------------------------------------------
# A05 詳細画面: 変更前後を読みやすい「項目・値」の一覧で表示する
# ------------------------------------------------------------

AUDIT_TARGET_LABELS = {
    "CorrectionRequest": "修正申請",
    "Employee": "社員",
    "EmploymentInfo": "雇用情報",
    "ExportBatch": "CSV出力",
    "NumberingLedger": "番号保全記録",
    "WorkSession": "勤務記録",
    "Department": "部署",
    "DepartmentRegistration": "部署登録",
    "MonthlyClosing": "月次確定",
}

AUDIT_FIELD_LABELS = {
    "clock_in_at": "出勤", "clock_out_at": "退勤", "breaks": "休憩",
    "started_at": "開始", "ended_at": "終了", "status": "状態", "proposal": "修正案",
    "work_date": "勤務日", "target_work_date": "移動先の勤務日", "original_version": "元の版",
    "version": "版", "related_request_id": "関連する旧申請", "is_proxy": "代理申請",
    "proxy_reason": "本人申請ができない理由", "evidence": "確認資料", "reason": "理由",
    "return_reason": "差戻し理由", "employee_number": "社員番号", "name": "名称・氏名",
    "first_name": "名", "last_name": "姓", "department": "部署", "code": "採番用コード",
    "is_active": "利用中", "is_business_admin": "業務管理者権限", "hire_date": "入社日",
    "retirement_date": "退職日", "target_month": "対象月", "month": "対象月",
    "output_id": "出力ID", "operation_id": "操作ID", "authenticated": "認証",
    "ip": "接続元IPアドレス", "count": "件数", "kind": "種別", "scope": "対象範囲",
}

AUDIT_STATUS_LABELS = {
    "pending": "審査中", "approved": "承認済み", "returned": "差戻し",
    "withdrawn": "取り下げ済み", "finalized": "確定済み", "reopened": "確定解除",
    "completed": "完了", "working": "勤務中", "on_break": "休憩中", "no_record": "記録なし",
}


def _audit_value(key, value):
    from django.utils.dateparse import parse_datetime

    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, bool):
        return "はい" if value else "いいえ"
    if key == "status" and isinstance(value, str):
        return AUDIT_STATUS_LABELS.get(value, value)
    if isinstance(value, str):
        parsed = parse_datetime(value) if "T" in value else None
        if parsed is not None:
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, JST)
            return timezone.localtime(parsed, JST).strftime("%Y/%m/%d %H:%M")
        parsed_day = parse_date(value) if len(value) == 10 else None
        if parsed_day is not None:
            return parsed_day.strftime("%Y/%m/%d")
        return value
    if isinstance(value, list):
        parts = []
        for entry in value:
            if isinstance(entry, dict) and ("started_at" in entry or "ended_at" in entry):
                parts.append(f"{_audit_value('started_at', entry.get('started_at'))}〜{_audit_value('ended_at', entry.get('ended_at'))}")
            else:
                parts.append(_audit_value(key, entry))
        return "、".join(parts)
    return str(value)


@register.filter
def audit_target_label(model_name):
    """対象の内部名（例: CorrectionRequest）を画面用の名称にする。"""
    return AUDIT_TARGET_LABELS.get(model_name or "", model_name or "—")


@register.filter
def audit_rows(data):
    """監査データ（dict）を [(項目名, 表示値), ...] に変換する。入れ子は1段だけ展開する。"""
    if not isinstance(data, dict) or not data:
        return []
    rows = []
    for key, value in data.items():
        label = AUDIT_FIELD_LABELS.get(key, key)
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                child_label = AUDIT_FIELD_LABELS.get(child_key, child_key)
                rows.append((f"{label}：{child_label}", _audit_value(child_key, child_value)))
        else:
            rows.append((label, _audit_value(key, value)))
    return rows
