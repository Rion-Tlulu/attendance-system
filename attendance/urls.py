from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path(
        "",
        views.home,
        name="home",
    ),
    path(
        "clock/",
        views.clock_action,
        name="clock_action",
    ),
]
