from .models import Notification


def notification_counts(request):
    if not request.user.is_authenticated:
        return {"notification_unread_count": 0}

    count = Notification.objects.filter(
        recipient=request.user,
        read_at__isnull=True,
    ).count()

    return {
        "notification_unread_count": count,
    }
