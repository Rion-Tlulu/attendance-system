from . import bulk_exports

from django.urls import path

from . import views

from . import employee_details
from . import proxy_corrections
from . import export_batches
from . import role_views
from . import department_views

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
    path(
        "employees/number-candidate/",
        views.employee_number_candidate,
        name="employee_number_candidate",
    ),
    # 社員情報の編集
    path(
        "employees/<int:employee_id>/edit/",
        views.employee_edit,
        name="employee_edit",
    ),
    path(
        "employees/<int:employee_id>/role/",
        role_views.employee_role,
        name="employee_role",
    ),
    path("roles/", role_views.role_list, name="role_list"),
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
        export_batches.single_month_batch,
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
    path(
        "employees/<int:employee_id>/employment/",
        employee_details.employement_edit,
        name="employment_edit",
    ),
    path(
        "employees/<int:employee_id>/months/<int:year>/<int:month>/proxy-correction/<int:day>/",
        proxy_corrections.proxy_correction,
        name="proxy_correction",
    ),
    path(
        "corrections/<int:pk>/withdraw/",
        proxy_corrections.proxy_withdraw,
        name="proxy_withdraw",
    ),
    # 全社員・部署別・個人別のCSV出力
    path(
        "exports/",
        bulk_exports.bulk_export,
        name="bulk_export",
    ),
    path("exports/<uuid:output_id>/", export_batches.batch_detail, name="batch_detail"),
    path(
        "exports/<uuid:output_id>/<str:output_format>/",
        export_batches.batch_download,
        name="batch_download",
    ),
    # 社員の初期パスワード再発行URL
    path(
        "employees/<int:employee_id>/reset-password/",
        views.employee_reset_password,
        name="employee_password_reset",
    ),
    # 部署関連
    path(
        "departments/",
        department_views.department_list,
        name="department_list",
    ),
    path(
        "departments/new/",
        department_views.department_create,
        name="department_create",
    ),
    path(
        "departments/registrations/<uuid:operation_id>/",
        department_views.department_registration_result,
        name="department_registration_result",
    ),
    path(
        "departments/<int:pk>/edit/",
        department_views.department_edit,
        name="department_edit",
    ),
]
