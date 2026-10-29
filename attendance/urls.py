from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    # Phase 5：打刻ホーム
    path(
        "",
        views.home,
        name="home",
    ),
    # Phase 5：打刻POST処理
    path(
        "clock/",
        views.clock_action,
        name="clock_action",
    ),
    # Phase 6：月次一覧
    path(
        "monthly/",
        views.monthly_attendance,
        name="monthly",
    ),
    # Phase 6：日別詳細
    path(
        "daily/<int:year>/<int:month>/<int:day>/",
        views.daily_attendance,
        name="daily",
    ),
]
