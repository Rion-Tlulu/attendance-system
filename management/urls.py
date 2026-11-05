from django.urls import path

from . import views

app_name = "management"

urlpatterns = [
    path(
        "",
        views.home,
        name="home",
    ),
    # 管理者勤怠一覧
    path(
        "attendance/",
        views.attendance_list,
        name="attendance_list",
    ),
    # 修正申請
    path(
        "corrections/",
        views.correction_queue,
        name="corrections",
    ),
    path(
        "corrections/<int:pk>/",
        views.correction_review_detail,
        name="correction_detail",
    ),
    path(
        "corrections/<int:pk>/review/",
        views.correction_review_submit,
        name="correction_review",
    ),
    # 社員管理
    path(
        "employees/",
        views.employee_list,
        name="employees",
    ),
    path(
        "employees/new/",
        views.employee_create,
        name="employee_create",
    ),
    # 社員情報の編集
    path(
        "employees/<int:employee_id>/edit/",
        views.employee_edit,
        name="employee_edit",
    ),
    # 社員別月次詳細
    path(
        "employees/<int:employee_id>/months/<int:year>/<int:month>/",
        views.employee_month,
        name="employee_month",
    ),
    # 月次確定・解除
    path(
        "employees/<int:employee_id>/months/<int:year>/<int:month>/finalize/",
        views.month_finalize,
        name="month_finalize",
    ),
    path(
        "employees/<int:employee_id>/months/<int:year>/<int:month>/reopen/",
        views.month_reopen,
        name="month_reopen",
    ),
    # CSV出力
    path(
        "employees/<int:employee_id>/months/<int:year>/<int:month>/csv/",
        views.month_csv,
        name="month_csv",
    ),
    # 操作履歴
    path(
        "audit/",
        views.audit_history,
        name="audit_history",
    ),
    path(
        "audit/<int:pk>/",
        views.audit_detail,
        name="audit_detail",
    ),
]
