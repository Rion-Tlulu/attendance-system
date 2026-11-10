from urllib.parse import urlsplit

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import (
    require_GET,
    require_POST,
)

from .models import Notification


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

    notifications = Notification.objects.filter(
        recipient=request.user,
    )

    status = request.GET.get("status", "all")

    if status == "unread":
        notifications = notifications.filter(
            read_at__isnull=True,
        )

    else:
        status = "all"

    unread_count = Notification.objects.filter(
        recipient=request.user,
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
@transaction.atomic
def notification_open(request, pk):
    """本人の通知を既読にして対象画面へ移動"""

    notification = get_object_or_404(
        Notification.objects.select_for_update(),
        pk=pk,
        recipient=request.user,
    )

    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])

    target = safe_notification_path(notification.target_path)

    return HttpResponseRedirect(target)


@never_cache
@login_required
@require_POST
def mark_all_read(request):
    """本人の未読通知だけを既読にする"""

    Notification.objects.filter(
        recipient=request.user,
        read_at__isnull=True,
    ).update(read_at=timezone.now())

    return HttpResponseRedirect(reverse("notifications:list"))
