from urllib.parse import urlsplit, urlencode, parse_qsl, urlunsplit

from django.core import signing
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import (
    require_GET,
    require_POST,
)

from config.db_errors import SAVE_FAILURE_ERRORS, UNCONFIRMED_SAVE_MESSAGE, log_save_failure

from .models import Notification
from .services import visible_notifications


def safe_notification_path(value):
    """アプリ内の相対パスだけを許可する"""

    if not isinstance(value, str):
        return reverse("notifications:list")

    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return reverse("notifications:list")

    parts = urlsplit(value)

    if parts.scheme or parts.netloc:
        return reverse("notifications:list")

    return value


@never_cache
@login_required
@require_GET
def notification_list(request):
    """本人に届いた通知を一覧表示する"""

    notifications = visible_notifications(request.user)

    status = request.GET.get("status", "all")

    if status == "unread":
        notifications = notifications.filter(
            read_at__isnull=True,
        )

    else:
        status = "all"

    unread_count = visible_notifications(request.user).filter(
        read_at__isnull=True,
    ).count()

    page_obj = Paginator(notifications, 20).get_page(request.GET.get("page"))

    return render(
        request,
        "notifications/list.html",
        {
            "page_obj": page_obj,
            "status_filter": status,
            "unread_count": unread_count,
        },
    )


@never_cache
@login_required
@require_POST
def notification_open(request, pk):
    """対象画面へ移動し、正常表示後にその通知だけ既読にする。"""

    notification = get_object_or_404(
        visible_notifications(request.user),
        pk=pk,
        recipient=request.user,
    )

    target = safe_notification_path(notification.target_path)
    parts = urlsplit(target)
    token = signing.dumps(
        {"notification_id": notification.pk, "recipient_id": request.user.pk},
        salt="attendance-notification-open-v1",
    )
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("_notification", token))
    return HttpResponseRedirect(urlunsplit(("", "", parts.path, urlencode(query), parts.fragment)))


@never_cache
@login_required
@require_POST
def mark_all_read(request):
    """本人の未読通知だけを既読にする"""

    started_at = timezone.now()
    try:
        visible_notifications(request.user).filter(
            read_at__isnull=True,
            created_at__lte=started_at,
        ).update(read_at=started_at)
    except SAVE_FAILURE_ERRORS:
        log_save_failure("notification_mark_all_read", employee_id=request.user.pk)
        messages.error(request, UNCONFIRMED_SAVE_MESSAGE)

    return HttpResponseRedirect(reverse("notifications:list"))


@never_cache
@login_required
@require_GET
def notification_panel(request):
    """右パネルの最新20件と未読件数を返す。"""
    notifications = visible_notifications(request.user)
    count = notifications.filter(read_at__isnull=True).count()
    if request.GET.get("status") == "unread":
        notifications = notifications.filter(read_at__isnull=True)
    items = list(notifications[:20])
    return JsonResponse({
        "unread_count": count,
        "items": [{
            "id": item.pk,
            "title": item.title,
            "body": item.body,
            "created_at": timezone.localtime(item.created_at).strftime("%Y/%m/%d %H:%M"),
            "read": item.is_read,
            "resolved": item.is_resolved,
            "workflow_label": item.workflow_label,
            "open_url": reverse("notifications:open", args=[item.pk]),
        } for item in items],
    })
