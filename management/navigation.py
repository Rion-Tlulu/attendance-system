"""一覧に戻る際の検索条件とページを、画面ごとに保持する。"""

from urllib.parse import urlencode

from django.shortcuts import redirect
from django.urls import reverse


def remember_list_query(request, name, fields):
    query = urlencode({
        field: request.GET[field][:200]
        for field in (*fields, "page") if request.GET.get(field)
    })
    request.session[f"{name}_return_query"] = query
    return query


def return_to_list(request, name, view_name):
    query = request.session.get(f"{name}_return_query", "")
    return redirect(reverse(view_name) + (f"?{query}" if query else ""))
