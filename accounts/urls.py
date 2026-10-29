from django.urls import path

from .views import (
    EmployeeLoginView,
    EmployeeLogoutView,
    EmployeePasswordChangeView,
)

from . import views as account_views

app_name = "accounts"

urlpatterns = [
    path(
        "login/",
        EmployeeLoginView.as_view(),
        name="login",
    ),
    path(
        "logout/",
        EmployeeLogoutView.as_view(),
        name="logout",
    ),
    path(
        "password/change/",
        EmployeePasswordChangeView.as_view(),
        name="password_change",
    ),
    # Phase8：アカウント情報
    path(
        "overview/",
        account_views.account_overview,
        name="overview",
    ),
    # Phase8：使い方ガイド
    path("guide/", account_views.usage_guide, name="guide"),
]
