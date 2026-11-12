"""既存部署と旧社員番号を部署別採番の履歴へ移す。"""

import json
import uuid
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from auditlog.models import AuditLog
from management.department_rules import normalize_department_name, used_department_codes
from management.models import Department, DepartmentRegistration, EmployeeNumberHistory, EmploymentInfo


class Command(BaseCommand):
    help = "確認済みの部署コード対応表を用いて既存社員と番号の履歴を移行します。"

    def add_arguments(self, parser):
        parser.add_argument("--mapping-file", required=True)
        parser.add_argument("--actor-number", required=True)
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            mapping = json.loads(Path(options["mapping_file"]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CommandError("部署コード対応表を読み取れません。") from exc
        if not isinstance(mapping, dict) or not mapping:
            raise CommandError("部署コード対応表は部署名からコードへのJSONオブジェクトです。")

        Employee = get_user_model()
        actor = Employee.objects.select_for_update().filter(
            employee_number=options["actor_number"], is_active=True,
            is_business_admin=True, is_staff=False, is_superuser=False,
        ).first()
        if actor is None:
            raise CommandError("有効な業務管理者を実行者に指定してください。")

        employees = list(Employee.objects.select_for_update().order_by("pk"))
        source_names = {
            normalize_department_name(employee.department)
            for employee in employees if employee.department.strip()
        }
        source_names.update(
            normalize_department_name(name)
            for name in EmploymentInfo.objects.exclude(department="").values_list("department", flat=True)
        )
        normalized = {}
        for raw_name, raw_code in mapping.items():
            name = normalize_department_name(raw_name)
            if name in normalized:
                raise CommandError("正規化後に重複する部署名があります。")
            if type(raw_code) is not int or not 1 <= raw_code <= 9:
                raise CommandError("部署コードは1〜9の整数で指定してください。")
            normalized[name] = raw_code
        if set(normalized) != source_names:
            raise CommandError(
                f"対応表と既存部署が一致しません。不足: {sorted(source_names-set(normalized))}、余分: {sorted(set(normalized)-source_names)}"
            )
        if len(set(normalized.values())) != len(normalized):
            raise CommandError("部署コードが重複しています。")

        existing = {dept.name: dept for dept in Department.objects.select_for_update()}
        used = used_department_codes()
        for name, code in normalized.items():
            department = existing.get(name)
            if department is not None:
                if department.code != code:
                    raise CommandError(f"{name}には別の部署コードが登録されています。")
            elif code in used:
                raise CommandError(f"コード{code}には既存・旧番号または登録履歴があります。")

        if options["dry_run"]:
            self.stdout.write(f"移行可能: 部署{len(normalized)}件、社員{len(employees)}件")
            return

        departments = {}
        for name, code in sorted(normalized.items(), key=lambda item: item[1]):
            department = existing.get(name)
            created = department is None
            if created:
                department = Department.objects.create(name=name, code=code, is_active=True)
            operation_id = uuid.uuid5(uuid.NAMESPACE_URL, f"legacy-department:{name}:{code}")
            registration, reg_created = DepartmentRegistration.objects.get_or_create(
                department=department,
                defaults={"actor": actor, "operation_id": operation_id,
                          "name": name, "code": code, "is_active": department.is_active},
            )
            if registration.name != name or registration.code != code:
                raise CommandError(f"{name}の登録履歴に不整合があります。")
            if created or reg_created:
                AuditLog.objects.create(
                    actor=actor, action=AuditLog.Action.DEPARTMENT_CREATE,
                    target_model=Department._meta.label, target_id=str(department.pk),
                    before_data={}, after_data={"name": name, "code": code,
                                                "is_active": department.is_active},
                    reason="既存部署の採番コード移行",
                    details={"operation_id": str(operation_id), "legacy_migration": True},
                )
            departments[name] = department

        for employee in employees:
            name = normalize_department_name(employee.department) if employee.department.strip() else None
            if name is None:
                raise CommandError(f"社員ID {employee.pk} の部署が未設定です。")
            department = departments[name]
            previous, created = EmployeeNumberHistory.objects.get_or_create(
                employee_number=employee.employee_number,
                defaults={"employee": employee, "department": department},
            )
            if previous.employee_id != employee.pk or previous.department_id != department.pk:
                raise CommandError(f"社員ID {employee.pk} の番号履歴に不整合があります。")
            employment = EmploymentInfo.objects.filter(employee=employee).first()
            if employment and not employment.department:
                employment.department = name
                employment.save(update_fields=["department"])
        self.stdout.write(self.style.SUCCESS(
            f"移行完了: 部署{len(departments)}件、社員番号履歴{len(employees)}件"
        ))
