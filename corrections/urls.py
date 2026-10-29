from django.urls import path
from . import views

app_name = "corrections"

urlpatterns = [
    path("", views.correction_list, name="list"),
    path(
        "<int:pk>/pk",
        views.correction_detail,
        name="detail",
    ),
    path(
        "<int:pk>/withdraw/",
        views.correction_withdraw,
        name="withdraw",
    ),
    path(
        "new/<int:year>/<int:month>/<int:day>/",
        views.correction_create,
        name="create",
    ),
]
