
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.cache import never_cache


@never_cache
@login_required
def home(request):
    """社員用の打刻ホーム（Phase 3では仮画面）。"""

    return render(
        request,
        "employee/home.html",
    )
