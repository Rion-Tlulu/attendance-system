"""Mark a notification read only after its destination rendered successfully."""

from urllib.parse import parse_qsl, urlsplit

from django.core import signing
from django.utils import timezone

from .services import visible_notifications


class NotificationDestinationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        token = request.GET.get("_notification")
        if (response.status_code != 200 or not token or user is None
                or not user.is_authenticated or request.method != "GET"):
            return response
        try:
            payload = signing.loads(
                token,
                salt="attendance-notification-open-v1",
                max_age=600,
            )
        except signing.BadSignature:
            return response
        if payload.get("recipient_id") != user.pk:
            return response
        notification = visible_notifications(user).filter(
            pk=payload.get("notification_id"), read_at__isnull=True,
        ).first()
        if notification is None:
            return response
        target = urlsplit(notification.target_path)
        actual_query = sorted(
            (key, value) for key, value in parse_qsl(request.META.get("QUERY_STRING", ""), keep_blank_values=True)
            if key != "_notification"
        )
        if request.path == target.path and actual_query == sorted(parse_qsl(target.query, keep_blank_values=True)):
            visible_notifications(user).filter(pk=notification.pk, read_at__isnull=True).update(
                read_at=timezone.now(),
            )
        return response
