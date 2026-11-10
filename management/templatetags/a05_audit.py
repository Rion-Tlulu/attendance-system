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

    date_from = parse_date(filters["from_date"])
    date_to = parse_date(filters["to_date"])

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
                "target_number": (getattr(target, "employee_number", "") or "—"),
                "reason": (getattr(log, "reason", "") or ""),
                "detail_url": _detail_url(log.pk),
            }
        )

    return {
        "allowed": True,
        "filters": filters,
        "errors": errors,
        "action_choices": action_choices,
        "total_count": paginator.count,
        "page_obj": page_obj,
        "rows": rows,
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
