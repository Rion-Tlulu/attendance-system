"""部署・社員番号のDB外保全と復元前の停止判定。"""

import json
import os
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils.dateparse import parse_datetime

from auditlog.models import AuditLog
from .models import Department, DepartmentRegistration, EmployeeNumberHistory, EmployeeNumberOperation


class NumberingLedgerError(Exception):
    pass


def _rows(model, *fields):
    queryset = model.objects if hasattr(model, "objects") else model
    return [dict(zip(fields, (
        value if value is None or isinstance(value, (str, int, float, bool, dict, list))
        else str(value) for value in row
    ))) for row in queryset.order_by("pk").values_list(*fields)]


def current_snapshot():
    return {
        "schema": 1,
        "departments": _rows(Department, "id", "name", "code", "is_active", "created_at"),
        "registrations": _rows(DepartmentRegistration, "id", "department_id", "actor_id",
                               "operation_id", "name", "code", "is_active", "created_at"),
        "numbers": _rows(EmployeeNumberHistory, "id", "department_id", "employee_id",
                         "employee_number", "issued_at"),
        "operations": _rows(EmployeeNumberOperation, "id", "actor_id", "employee_id",
                            "operation_id", "kind", "request_data", "issued_number", "created_at"),
        "department_audits": _rows(
            AuditLog.objects.filter(action=AuditLog.Action.DEPARTMENT_CREATE),
            "id", "actor_id", "action", "target_model", "target_id", "before_data",
            "after_data", "reason", "details", "occurred_at",
        ),
    }


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@contextmanager
def _file_lock(path):
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"0")
                handle.flush()
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_locked(path):
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        payload = document["payload"]
        signature = document["signature"]
        signer = signing.Signer(salt="attendance-numbering-ledger-v1")
        if signer.signature(_canonical(payload)) != signature:
            raise NumberingLedgerError("保全記録の署名が一致しません。")
        if payload.get("schema") != 1:
            raise NumberingLedgerError("保全記録の形式が不明です。")
        return payload
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise NumberingLedgerError("保全記録を読み取れません。") from exc


def read_snapshot(path=None):
    path = Path(path or settings.NUMBERING_LEDGER_PATH)
    with _file_lock(path):
        return _read_locked(path)


def _write_locked(path, payload):
    document = {"payload": payload, "signature": signing.Signer(
        salt="attendance-numbering-ledger-v1"
    ).signature(_canonical(payload))}
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(_canonical(document), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def export_snapshot(path=None):
    path = Path(path or settings.NUMBERING_LEDGER_PATH)
    with _file_lock(path):
        payload = current_snapshot()
        _write_locked(path, payload)
    return payload


def verify_snapshot(path=None):
    path = Path(path or settings.NUMBERING_LEDGER_PATH)
    with _file_lock(path):
        expected = _read_locked(path)
        actual = current_snapshot()
    if expected != actual:
        raise NumberingLedgerError("部署・番号の保全記録とDBが一致しません。復元照合まで採番を停止します。")
    return expected


def _test_database():
    name = str(connection.settings_dict["NAME"])
    return name.startswith("test_") or name.startswith("file:memorydb_")


def require_numbering_ready():
    if _test_database():
        return
    try:
        verify_snapshot()
    except NumberingLedgerError as exc:
        raise ValidationError(str(exc)) from exc


def reserve_pending(*, kind, value, actor_id, operation_id):
    """DB確定前にコード・番号の使用予定をDB外へ記録する。

    DBがロールバックされた場合も保全記録を残し、照合まで新規採番を止める。
    """
    if _test_database():
        return
    path = Path(settings.NUMBERING_LEDGER_PATH)
    with _file_lock(path):
        try:
            expected = _read_locked(path)
        except NumberingLedgerError as exc:
            raise ValidationError(str(exc)) from exc
        if expected != current_snapshot():
            raise ValidationError("番号保全記録の未照合操作があります。部署登録と採番を停止します。")
        pending = {
            **expected,
            "pending": [{
                "kind": kind, "value": str(value), "actor_id": actor_id,
                "operation_id": str(operation_id),
            }],
        }
        _write_locked(path, pending)


def cancel_pending(*, kind, operation_id, path=None):
    """確定前にDBがロールバックされた操作の保留だけを解除する。"""
    if _test_database():
        return False
    path = Path(path or settings.NUMBERING_LEDGER_PATH)
    with _file_lock(path):
        saved = _read_locked(path)
        pending_list = saved.get("pending", [])
        if len(pending_list) != 1 or pending_list[0]["kind"] != kind or (
            pending_list[0]["operation_id"] != str(operation_id)
        ):
            return False
        previous = {key: value for key, value in saved.items() if key != "pending"}
        if current_snapshot() != previous:
            raise NumberingLedgerError("DBの状態が変わりました。保留記録を解除できません。")
        _write_locked(path, previous)
        return True


@transaction.atomic
def reconcile_pending(*, actor, reason, path=None):
    """確定済みの操作を照合し、保留記録を解除したことを監査する。"""
    path = Path(path or settings.NUMBERING_LEDGER_PATH)
    from django.contrib.auth import get_user_model
    Employee = get_user_model()
    restorer = Employee.objects.select_for_update().get(pk=actor.pk)
    if not restorer.is_active or not restorer.is_business_admin:
        raise NumberingLedgerError("再開には有効な業務管理者が必要です。")
    if not 1 <= len(reason.strip()) <= 500:
        raise NumberingLedgerError("再開理由を1〜500文字で入力してください。")
    with _file_lock(path):
        saved = _read_locked(path)
        pending_list = saved.get("pending", [])
        if len(pending_list) != 1:
            raise NumberingLedgerError("照合対象の保留操作が1件ではありません。")
        pending = pending_list[0]
        previous = {key: value for key, value in saved.items() if key != "pending"}
        actual = current_snapshot()
        kind = pending["kind"]
        for key, old_rows in previous.items():
            if key == "schema":
                if old_rows != actual[key]:
                    raise NumberingLedgerError("保全記録の形式が一致しません。")
                continue
            actual_by_id = {row["id"]: row for row in actual[key]}
            for row in old_rows:
                current = actual_by_id.get(row["id"])
                if kind == "department_edit" and key == "departments" and str(row["id"]) == pending["value"]:
                    if current is None or current["code"] != row["code"]:
                        raise NumberingLedgerError("部署の変更結果を照合できません。")
                elif current != row:
                    raise NumberingLedgerError("保全記録の既存履歴がDBと一致しません。")

        operation_id = pending["operation_id"]
        if kind == "department_create":
            registration = DepartmentRegistration.objects.filter(
                actor_id=pending["actor_id"], operation_id=operation_id,
                code=int(pending["value"]),
            ).first()
            valid = bool(registration and AuditLog.objects.filter(
                action=AuditLog.Action.DEPARTMENT_CREATE,
                target_id=str(registration.department_id),
                details__operation_id=operation_id,
            ).exists())
        elif kind in {"employee_create", "employee_edit"}:
            operation = EmployeeNumberOperation.objects.filter(
                actor_id=pending["actor_id"], operation_id=operation_id,
                kind="create" if kind == "employee_create" else "edit",
                issued_number=pending["value"],
            ).first()
            valid = bool(operation and EmployeeNumberHistory.objects.filter(
                employee_id=operation.employee_id,
                employee_number=pending["value"],
            ).exists())
        elif kind == "department_edit":
            valid = AuditLog.objects.filter(
                actor_id=pending["actor_id"],
                action=AuditLog.Action.DEPARTMENT_UPDATE,
                target_id=pending["value"],
                details__operation_id=operation_id,
            ).exists()
        else:
            valid = False
        if not valid or actual == previous:
            raise NumberingLedgerError("保留操作の確定結果を照合できません。採番を停止します。")

    AuditLog.objects.create(
        actor=restorer, action=AuditLog.Action.DEPARTMENT_UPDATE,
        target_model="NumberingLedger", target_id="1",
        before_data={"pending": pending}, after_data={"verified": True},
        reason=reason.strip(), details={"ledger_path": str(path)},
    )
    transaction.on_commit(lambda: export_snapshot(path))
    return actual


def sync_after_commit():
    if not _test_database():
        transaction.on_commit(export_snapshot)


@transaction.atomic
def restore_departments(*, path=None, actor):
    """発行履歴に欠損がない場合だけ、DBバックアップ後の部署と操作結果を復元する。"""
    path = Path(path or settings.NUMBERING_LEDGER_PATH)
    expected = read_snapshot(path)
    from django.contrib.auth import get_user_model
    Employee = get_user_model()
    restorer = Employee.objects.select_for_update().get(pk=actor.pk)
    if not restorer.is_active or not restorer.is_business_admin:
        raise NumberingLedgerError("復元再開には有効な業務管理者が必要です。")
    actual = current_snapshot()
    if actual["operations"] != expected["operations"]:
        raise NumberingLedgerError("社員の採番操作結果が一致しません。採番を停止します。")

    for row in expected["departments"]:
        existing = Department.objects.filter(pk=row["id"]).first()
        if existing is None:
            if Department.objects.filter(name=row["name"]).exists() or Department.objects.filter(code=row["code"]).exists():
                raise NumberingLedgerError("部署ID・名称・コードに衝突があります。")
            Department.objects.create(pk=row["id"], name=row["name"], code=row["code"],
                                      is_active=row["is_active"])
            Department.objects.filter(pk=row["id"]).update(created_at=parse_datetime(row["created_at"]))
        elif (existing.name, existing.code, existing.is_active) != (row["name"], row["code"], row["is_active"]):
            raise NumberingLedgerError("復元済み部署の内容に衝突があります。")

    expected_numbers_by_employee = {}
    for row in expected["numbers"]:
        expected_numbers_by_employee.setdefault(row["employee_id"], set()).add(row["employee_number"])
    for row in expected["numbers"]:
        existing = EmployeeNumberHistory.objects.filter(pk=row["id"]).first()
        if existing is None:
            employee = Employee.objects.filter(pk=row["employee_id"]).first()
            if employee is None or employee.employee_number not in expected_numbers_by_employee[row["employee_id"]]:
                raise NumberingLedgerError("発行済み番号と社員の照合ができません。採番を停止します。")
            if EmployeeNumberHistory.objects.filter(employee_number=row["employee_number"]).exists():
                raise NumberingLedgerError("発行済み番号の履歴に衝突があります。採番を停止します。")
            EmployeeNumberHistory.objects.create(
                pk=row["id"], department_id=row["department_id"],
                employee_id=row["employee_id"], employee_number=row["employee_number"],
            )
            EmployeeNumberHistory.objects.filter(pk=row["id"]).update(
                issued_at=parse_datetime(row["issued_at"])
            )
        elif (existing.department_id, existing.employee_id, existing.employee_number) != (
            row["department_id"], row["employee_id"], row["employee_number"]
        ):
            raise NumberingLedgerError("発行済み番号の履歴に衝突があります。採番を停止します。")

    for row in expected["registrations"]:
        existing = DepartmentRegistration.objects.filter(pk=row["id"]).first()
        if existing is None:
            if not Employee.objects.filter(pk=row["actor_id"]).exists():
                raise NumberingLedgerError("登録実行者の証跡がありません。")
            DepartmentRegistration.objects.create(
                pk=row["id"], department_id=row["department_id"], actor_id=row["actor_id"],
                operation_id=row["operation_id"], name=row["name"], code=row["code"],
                is_active=row["is_active"],
            )
            DepartmentRegistration.objects.filter(pk=row["id"]).update(
                created_at=parse_datetime(row["created_at"])
            )
        elif (existing.department_id, existing.actor_id, str(existing.operation_id), existing.name,
              existing.code, existing.is_active) != (
                  row["department_id"], row["actor_id"], row["operation_id"], row["name"],
                  row["code"], row["is_active"]):
            raise NumberingLedgerError("登録操作結果に衝突があります。")

    for row in expected["department_audits"]:
        existing = AuditLog.objects.filter(pk=row["id"]).first()
        if existing is None:
            if not Employee.objects.filter(pk=row["actor_id"]).exists():
                raise NumberingLedgerError("監査実行者の証跡がありません。")
            AuditLog.objects.create(
                pk=row["id"], actor_id=row["actor_id"], action=row["action"],
                target_model=row["target_model"], target_id=row["target_id"],
                before_data=row["before_data"], after_data=row["after_data"],
                reason=row["reason"], details=row["details"],
                occurred_at=parse_datetime(row["occurred_at"]),
            )
        elif (existing.actor_id, existing.action, existing.target_model, existing.target_id,
              existing.before_data, existing.after_data, existing.reason, existing.details) != (
                  row["actor_id"], row["action"], row["target_model"], row["target_id"],
                  row["before_data"], row["after_data"], row["reason"], row["details"]):
            raise NumberingLedgerError("A05の成功履歴に衝突があります。")

    if current_snapshot() != expected:
        raise NumberingLedgerError("復元後の照合に失敗しました。採番を停止します。")
    if connection.vendor == "postgresql":
        from django.core.management.color import no_style
        statements = connection.ops.sequence_reset_sql(
            no_style(), [Department, DepartmentRegistration, EmployeeNumberHistory, AuditLog]
        )
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
    AuditLog.objects.create(
        actor=restorer, action=AuditLog.Action.DEPARTMENT_UPDATE,
        target_model="NumberingLedger", target_id="1", before_data={},
        after_data={"verified": True}, reason="部署・番号の保全記録とDBを照合して再開",
        details={"ledger_path": str(path)},
    )
    return expected
