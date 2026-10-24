
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    path(
        "",
        RedirectView.as_view(
            pattern_name="attendance:home",
            permanent=False,
        ),
        name="index",
    ),
    path(
        "accounts/",
        include("accounts.urls"),
    ),
    path(
        "employee/",
        include("attendance.urls"),
    ),
    path(
        "management/",
        include("management.urls"),
    ),
    path(
        "admin/",
        admin.site.urls,
    ),
]
