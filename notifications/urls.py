from django.urls import path

from . import views

app_name = "notifications"


urlpatterns = [
    path("panel/", views.notification_panel, name="panel"),
    # 通知一覧
    path(
        "",
        views.notification_list,
        name="list",
    ),
    # 通知を開いて既読にする
    path(
        "<int:pk>/open/",
        views.notification_open,
        name="open",
    ),
    # 通知をすべて既読にする
    path(
        "read-all/",
        views.mark_all_read,
        name="read_all",
    ),
]
