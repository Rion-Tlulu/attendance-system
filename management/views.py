
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from accounts.decorators import business_admin_required


@never_cache
@business_admin_required
def home(request):
    """管理者用ホーム（Phase 3では仮画面）。"""

    return render(
        request,
        "management/home.html",
    )
