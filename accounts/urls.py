from django.urls import path

from .views import (
    EmployeeLoginView,
    EmployeeLogoutView,
    EmployeePasswordChangeView,
)


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
]