from .models import Notification
from .services import visible_notifications


def notification_counts(request):
    if not request.user.is_authenticated:
        return {"notification_unread_count": 0}

    count = visible_notifications(request.user).filter(
        read_at__isnull=True,
    ).count()

    return {
        "notification_unread_count": count,
    }
