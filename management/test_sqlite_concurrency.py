"""SQLite（ファイル DB・IMMEDIATE）での同時実行とロック失敗時の整合性試験。

以前はスキップされていた同時実行の試験11件を、SQLite 版として置き換えたもの。

前提（config/settings.py）:
- SQLite は select_for_update を無視し、書き込みは DB 全体で1つずつになる。
- transaction_mode=IMMEDIATE のため、atomic の開始時に書き込みロックを取り、
  後続のトランザクションは開始時点で最大 timeout 秒待たされる。

試験の構成:
1. SQLiteConcurrencyTests        Barrier で2スレッドを同時送信（旧11件の置き換え）
2. SQLiteSerializationOrderTests  判定と書き込みの間で先行を止め、後続が待たされる順序を固定
3. SQLiteLockFailureIntegrityTests 別接続でロックを握り、database is locked 時の整合性を確認

インメモリのテスト DB（共有キャッシュ）ではロック挙動が本番と異なるため実行しない。
manage.py test は config/settings_test.py によりファイル DB を使う。
"""

import sqlite3
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from threading import Barrier
from unittest import SkipTest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import OperationalError, close_old_connections, connection
from django.db.models import Count
from django.test import Client, TransactionTestCase, override_settings, tag
from django.urls import reverse
from django.utils import timezone

from accounts.models import Employee as EmployeeModel
from attendance import services as attendance_services
from attendance.models import (
    ClockEvent,
    IncompleteOccurrence,
    MonthlyClosing,
    WorkSession,
)
from attendance.services import ClockActionError, record_clock_action
from auditlog.models import AuditLog
from config.db_errors import UNCONFIRMED_SAVE_MESSAGE
from corrections.models import CorrectionRequest
from corrections.services import CorrectionError, current_values, withdraw_correction
from management import services as management_services
from management import views as management_views
from management.models import (
    Department,
    DepartmentRegistration,
    EmployeeNumberHistory,
    EmployeeNumberOperation,
    EmploymentInfo,
    ExportBatch,
)
from management.numbering_ledger import (
    NumberingLedgerError,
    cancel_pending,
    export_snapshot,
    read_snapshot,
    require_numbering_ready,
    reserve_pending,
    verify_snapshot,
)
from management.reconciliation import reconciliation_token
from management.role_management import RoleChangeError, change_business_admin_role
from management.services import AdminActionError, finalize_month, reopen_month, review_correction
from notifications.models import Notification
from notifications.services import create_notification

JST = ZoneInfo("Asia/Tokyo")
PASSWORD = "TestPassword_2026!"
TARGET_MONTH = date(2026, 9, 1)


# ==========================================
# 共通基盤
# ==========================================


@tag("sqlite_concurrency")
class SQLiteFileDatabaseTestCase(TransactionTestCase):
    """ファイル DB の SQLite でだけ実行し、各試験後に DB 全体の不変条件を確認する。"""

    @classmethod
    def setUpClass(cls):
        if connection.vendor != "sqlite" or connection.is_in_memory_db():
            raise SkipTest(
                "ファイル DB の SQLite が必要です（manage.py test は config.settings_test を使用）。"
            )
        super().setUpClass()

    def setUp(self):
        self.manager = get_user_model().objects.create_user(
            employee_number="91001", password=PASSWORD, is_business_admin=True,
        )

    def tearDown(self):
        close_old_connections()
        self.assert_database_invariants()
        super().tearDown()

    # ---- データ作成 ----

    def create_admin(self, number, **extra):
        return get_user_model().objects.create_user(
            employee_number=number, password=PASSWORD, is_business_admin=True, **extra,
        )

    def create_employee(self, number="91004", **extra):
        extra.setdefault("hire_date", date(2026, 1, 1))
        return get_user_model().objects.create_user(
            employee_number=number, password=PASSWORD, **extra,
        )

    def create_completed_session(self, employee, day=date(2026, 9, 15)):
        return WorkSession.objects.create(
            employee=employee, work_date=day,
            clock_in_at=datetime(day.year, day.month, day.day, 9, tzinfo=JST),
            clock_out_at=datetime(day.year, day.month, day.day, 18, tzinfo=JST),
            status=WorkSession.Status.COMPLETED,
        )

    def create_pending_correction(self, employee, work):
        proposal = current_values(work)
        proposal["clock_out_at"] = datetime(
            work.work_date.year, work.work_date.month, work.work_date.day, 18, 30, tzinfo=JST,
        ).isoformat()
        return CorrectionRequest.objects.create(
            work_session=work, employee=employee, work_date=work.work_date,
            requested_by=employee, original_version=work.version,
            proposal=proposal, reason="退勤の訂正", status=CorrectionRequest.Status.PENDING,
        )

    def logged_in_client(self, user=None):
        client = Client()
        client.force_login(user or self.manager)
        return client

    # ---- 不変条件 ----

    def assert_active_admin_count(self, expected):
        self.assertEqual(
            get_user_model().objects.filter(is_active=True, is_business_admin=True).count(),
            expected,
        )

    def assert_database_invariants(self):
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA integrity_check")
            self.assertEqual(cursor.fetchone()[0], "ok")
            cursor.execute("PRAGMA foreign_key_check")
            self.assertEqual(cursor.fetchall(), [])

        Employee = get_user_model()
        # 社員番号: 現行番号は重複せず、発行済み番号は発行先以外の社員が使わない。
        holders = dict(Employee.objects.values_list("employee_number", "pk"))
        self.assertEqual(len(holders), Employee.objects.count())
        for number, owner_id in EmployeeNumberHistory.objects.values_list(
            "employee_number", "employee_id",
        ):
            if number in holders:
                self.assertEqual(holders[number], owner_id, f"社員番号 {number} の発行先が不一致")

        # 打刻: 進行中の勤務は社員ごとに1件まで、操作IDごとに打刻は1件まで。
        self.assertFalse(
            WorkSession.objects.filter(
                status__in=[WorkSession.Status.WORKING, WorkSession.Status.ON_BREAK],
            ).values("employee").annotate(n=Count("pk")).filter(n__gt=1).exists()
        )
        self.assertFalse(
            ClockEvent.objects.values("operation_id").annotate(n=Count("pk")).filter(n__gt=1).exists()
        )

        # 月次確定: 確定済みの月はスナップショットが確定時点の勤務と一致する。
        for closing in MonthlyClosing.objects.filter(status=MonthlyClosing.Status.FINALIZED):
            self.assertIsNotNone(closing.finalized_by_id)
            self.assertEqual(closing.snapshot.get("data_version"), closing.version)
            self.assertEqual(closing.integrity_check_result.get("data_version"), closing.version)
            sessions = {
                item.work_date.isoformat(): item for item in WorkSession.objects.filter(
                    employee=closing.employee,
                    work_date__year=closing.target_month.year,
                    work_date__month=closing.target_month.month,
                )
            }
            for row in closing.snapshot["daily"]:
                session = sessions.get(row["day"])
                self.assertEqual(row["session_version"], session.version if session else None)
                self.assertEqual(
                    row["clock_in_at"],
                    session.clock_in_at.isoformat() if session and session.clock_in_at else None,
                )
                self.assertEqual(
                    row["clock_out_at"],
                    session.clock_out_at.isoformat() if session and session.clock_out_at else None,
                )

    # ---- スレッド実行 ----

    @staticmethod
    def _in_thread(func):
        close_old_connections()
        try:
            try:
                return func()
            except Exception as exc:  # 結果として呼び出し元で判定する
                return exc
        finally:
            close_old_connections()

    def run_concurrently(self, *funcs):
        """Barrier で開始を揃えて同時に実行し、戻り値または例外を返す。"""
        barrier = Barrier(len(funcs))

        def run(func):
            def body():
                barrier.wait(timeout=15)
                return func()
            return self._in_thread(body)

        with ThreadPoolExecutor(max_workers=len(funcs)) as pool:
            futures = [pool.submit(run, func) for func in funcs]
            return [future.result(timeout=60) for future in futures]

    def run_first_then_second(self, first, second, *, pause_owner, pause_name):
        """first を pause_owner.pause_name の呼出時点（書き込みロック保持中）で止めて second を開始する。

        second が first の確定まで待たされていることを確認してから first を再開する。
        """
        original = getattr(pause_owner, pause_name)
        paused, release = threading.Event(), threading.Event()
        first_thread = []

        def wrapper(*args, **kwargs):
            if first_thread and threading.get_ident() == first_thread[0] and not paused.is_set():
                paused.set()
                if not release.wait(timeout=30):
                    raise RuntimeError("先行処理の再開待ちがタイムアウトしました。")
            return original(*args, **kwargs)

        def run_first():
            first_thread.append(threading.get_ident())
            return self._in_thread(first)

        with patch.object(pause_owner, pause_name, new=wrapper), \
                ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(run_first)
            try:
                self.assertTrue(paused.wait(timeout=15), "先行処理が停止位置に到達しませんでした。")
                second_future = pool.submit(self._in_thread, second)
                time.sleep(0.5)
                self.assertFalse(
                    second_future.done(),
                    "後続処理が先行処理の確定を待たずに終了しました（直列化されていません）。",
                )
            finally:
                release.set()
            return first_future.result(timeout=60), second_future.result(timeout=60)

    # ---- ロック注入 ----

    def db_path(self):
        return str(connection.settings_dict["NAME"])

    @contextmanager
    def lock_from_other_connection(self, mode):
        """別接続でロックを保持する。

        write: BEGIN IMMEDIATE で書き込みロックを保持する（対象処理は開始時点で失敗する）。
        read:  読み取りトランザクションを保持する（DELETE ジャーナルでは COMMIT 時に失敗する）。
        """
        other = sqlite3.connect(self.db_path(), isolation_level=None, timeout=1)
        try:
            if mode == "write":
                other.execute("BEGIN IMMEDIATE")
            else:
                other.execute("BEGIN")
                other.execute("SELECT count(*) FROM django_migrations").fetchone()
            yield
        finally:
            other.execute("ROLLBACK")
            other.close()

    @contextmanager
    def short_busy_timeout(self, milliseconds=200):
        default = int(float(settings.DATABASES["default"].get("OPTIONS", {}).get("timeout", 5)) * 1000)
        with connection.cursor() as cursor:
            cursor.execute(f"PRAGMA busy_timeout = {int(milliseconds)}")
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f"PRAGMA busy_timeout = {default}")

    @contextmanager
    def locked(self, mode):
        if mode == "read":
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA journal_mode")
                journal_mode = cursor.fetchone()[0].lower()
            if journal_mode == "wal":
                self.skipTest("WAL では読み取りが COMMIT を妨げないため対象外です。")
        with self.short_busy_timeout(), self.lock_from_other_connection(mode):
            yield

    @contextmanager
    def numbering_ledger_enabled(self):
        """番号保全台帳を一時フォルダで有効にする。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            with override_settings(NUMBERING_LEDGER_PATH=path), patch(
                "management.numbering_ledger._test_database", return_value=False,
            ):
                export_snapshot(path)
                yield path

    def assert_ledger_has_no_pending(self, path):
        self.assertNotIn("pending", read_snapshot(path))
        verify_snapshot(path)


# ==========================================
# 1. 同時送信（以前スキップされていた同時実行試験11件の置き換え）
# ==========================================


class SQLiteConcurrencyTests(SQLiteFileDatabaseTestCase):
    """2スレッドで同時に送信し、後続が先行の確定を待ってから判定されることを確認する。"""

    def concurrent_posts(self, requests):
        clients = [self.logged_in_client() for _ in requests]
        results = self.run_concurrently(*[
            (lambda client=client, url=url, data=data: client.post(url, data).status_code)
            for client, (url, data) in zip(clients, requests)
        ])
        for result in results:
            if isinstance(result, Exception):
                raise result
        return results

    def test_a07_same_code_concurrent_registration_writes_one_history(self):
        url = reverse("management:department_create")
        responses = self.concurrent_posts([
            (url, {"name": "営業部", "code": "3", "is_active": "on", "operation_id": str(uuid.uuid4())}),
            (url, {"name": "総務部", "code": "3", "is_active": "on", "operation_id": str(uuid.uuid4())}),
        ])
        self.assertEqual(responses.count(302), 1)
        self.assertTrue(all(status in {200, 302, 409} for status in responses))
        self.assertEqual(Department.objects.filter(code=3).count(), 1)
        self.assertEqual(DepartmentRegistration.objects.filter(code=3).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.DEPARTMENT_CREATE).count(), 1)

    def test_a07_same_normalized_name_concurrent_registration_writes_one_history(self):
        url = reverse("management:department_create")
        responses = self.concurrent_posts([
            (url, {"name": "  開発部  ", "code": "3", "is_active": "on", "operation_id": str(uuid.uuid4())}),
            (url, {"name": "開発部", "code": "4", "is_active": "on", "operation_id": str(uuid.uuid4())}),
        ])
        self.assertEqual(responses.count(302), 1)
        self.assertTrue(all(status in {200, 302, 409} for status in responses))
        self.assertEqual(Department.objects.count(), 1)
        self.assertEqual(DepartmentRegistration.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.DEPARTMENT_CREATE).count(), 1)

    def test_a07_concurrency_with_external_ledger_keeps_one_result(self):
        with self.numbering_ledger_enabled() as path:
            url = reverse("management:department_create")
            responses = self.concurrent_posts([
                (url, {"name": "営業部", "code": "3", "is_active": "on",
                       "operation_id": str(uuid.uuid4())}),
                (url, {"name": "総務部", "code": "3", "is_active": "on",
                       "operation_id": str(uuid.uuid4())}),
            ])
            self.assertEqual(responses.count(302), 1)
            self.assertTrue(all(status in {200, 302, 409, 503} for status in responses))
            self.assertEqual(len(verify_snapshot(path)["departments"]), 1)
            self.assertEqual(DepartmentRegistration.objects.count(), 1)
            self.assertEqual(AuditLog.objects.filter(
                action=AuditLog.Action.DEPARTMENT_CREATE,
            ).count(), 1)

    def test_a03_simultaneous_creates_get_distinct_numbers(self):
        department = Department.objects.create(name="開発部", code=3)
        url = reverse("management:employee_create")
        responses = self.concurrent_posts([
            (url, {"first_name": "太郎", "last_name": "佐藤", "department_choice": str(department.pk),
                   "hire_date": "2026-04-01", "operation_id": str(uuid.uuid4())}),
            (url, {"first_name": "花子", "last_name": "山田", "department_choice": str(department.pk),
                   "hire_date": "2026-04-01", "operation_id": str(uuid.uuid4())}),
        ])
        self.assertEqual(responses, [200, 200])
        self.assertEqual(set(EmployeeNumberHistory.objects.values_list("employee_number", flat=True)),
                         {"30001", "30002"})

    def test_a06_simultaneous_revocations_keep_two_active_managers(self):
        first = self.create_admin("91002")
        second = self.create_admin("91003")
        responses = self.concurrent_posts([
            (reverse("management:employee_role", args=[first.pk]),
             {"expected_role": "admin", "desired_role": "employee", "change_reason": "交代"}),
            (reverse("management:employee_role", args=[second.pk]),
             {"expected_role": "admin", "desired_role": "employee", "change_reason": "交代"}),
        ])
        self.assertEqual(sorted(responses), [200, 302])
        self.assert_active_admin_count(2)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.ROLE_CHANGE).count(), 1)

    def test_t02_parallel_clock_replay_writes_one_event(self):
        employee = self.create_employee()
        today = timezone.localdate()
        operation_id = uuid.uuid4()

        def clock():
            return record_clock_action(
                employee_id=employee.pk, kind=ClockEvent.Kind.CLOCK_IN,
                operation_id=operation_id, expected_work_date=today,
            )

        results = self.run_concurrently(clock, clock)
        for result in results:
            if isinstance(result, Exception):
                raise result
        self.assertEqual(ClockEvent.objects.filter(operation_id=operation_id).count(), 1)
        self.assertEqual(WorkSession.objects.filter(employee=employee).count(), 1)
        self.assertEqual(sorted(result.already_recorded for result in results), [False, True])

    def test_t02_parallel_distinct_clock_ins_reject_second(self):
        employee = self.create_employee()
        today = timezone.localdate()

        def clock():
            return record_clock_action(
                employee_id=employee.pk, kind=ClockEvent.Kind.CLOCK_IN,
                operation_id=uuid.uuid4(), expected_work_date=today,
            )

        results = self.run_concurrently(clock, clock)
        self.assertFalse(any(isinstance(item, OperationalError) for item in results), results)
        self.assertEqual(sum(isinstance(item, ClockActionError) for item in results), 1)
        self.assertEqual(ClockEvent.objects.filter(kind=ClockEvent.Kind.CLOCK_IN).count(), 1)

    def test_t04_parallel_withdrawal_and_approval_have_one_outcome(self):
        employee = self.create_employee()
        work = self.create_completed_session(employee)
        correction = self.create_pending_correction(employee, work)

        def approve():
            review_correction(manager_id=self.manager.pk, correction_id=correction.pk, action="approve")
            return "success"

        def withdraw():
            withdraw_correction(employee_id=employee.pk, request_id=correction.pk)
            return "success"

        results = self.run_concurrently(approve, withdraw)
        self.assertFalse(any(isinstance(item, OperationalError) for item in results), results)
        outcomes = sorted(
            "rejected" if isinstance(item, (AdminActionError, CorrectionError)) else item
            for item in results
        )
        self.assertEqual(outcomes, ["rejected", "success"])
        correction.refresh_from_db()
        self.assertIn(correction.status, {
            CorrectionRequest.Status.APPROVED, CorrectionRequest.Status.WITHDRAWN,
        })
        work.refresh_from_db()
        self.assertEqual(work.version, 2 if correction.status == CorrectionRequest.Status.APPROVED else 1)

    def test_t05_parallel_month_finalization_keeps_one_current_version(self):
        employee = self.create_employee()

        def finalize():
            finalize_month(
                manager_id=self.manager.pk, employee_id=employee.pk,
                target_month=TARGET_MONTH, checked_no_record=True,
            )
            return "success"

        results = self.run_concurrently(finalize, finalize)
        self.assertFalse(any(isinstance(item, OperationalError) for item in results), results)
        outcomes = sorted("rejected" if isinstance(item, AdminActionError) else item for item in results)
        self.assertEqual(outcomes, ["rejected", "success"])
        self.assertEqual(MonthlyClosing.objects.filter(
            employee=employee, target_month=TARGET_MONTH,
            status=MonthlyClosing.Status.FINALIZED,
        ).count(), 1)

    def test_t17_parallel_stop_and_revoke_keep_two_managers(self):
        department = Department.objects.create(name="総務部", code=1)
        first = self.create_admin("91002", department=department.name)
        second = self.create_admin("91003", department=department.name)
        edit_url = reverse("management:employee_edit", args=[second.pk])
        edit_state = self.logged_in_client().get(edit_url).context["edit_state"]
        responses = self.concurrent_posts([
            (reverse("management:employee_role", args=[first.pk]),
             {"expected_role": "admin", "desired_role": "employee", "change_reason": "交代"}),
            (edit_url, {
                "employee_number": second.employee_number, "first_name": "Test",
                "last_name": "Manager", "department_choice": str(department.pk),
                "change_reason": "交代", "edit_state": edit_state,
                "operation_id": str(uuid.uuid4()),
            }),
        ])
        self.assertEqual(sorted(responses), [200, 302])
        self.assert_active_admin_count(2)

    def test_t18_parallel_transfers_issue_distinct_numbers(self):
        source = Department.objects.create(name="旧部署", code=1)
        target = Department.objects.create(name="新部署", code=3)
        employees = [
            self.create_employee(
                f"1000{index}", first_name=f"社員{index}", last_name="試験", department=source.name,
            ) for index in (1, 2)
        ]
        for employee in employees:
            EmployeeNumberHistory.objects.create(
                employee=employee, department=source, employee_number=employee.employee_number,
            )
        client = self.logged_in_client()
        requests = []
        for employee in employees:
            url = reverse("management:employee_edit", args=[employee.pk])
            state = client.get(url).context["edit_state"]
            requests.append((url, {
                "employee_number": employee.employee_number,
                "first_name": employee.first_name,
                "last_name": employee.last_name,
                "department_choice": str(target.pk), "is_active": "on",
                "change_reason": "異動", "edit_state": state,
                "operation_id": str(uuid.uuid4()),
            }))
        self.assertEqual(self.concurrent_posts(requests), [302, 302])
        self.assertEqual(set(get_user_model().objects.filter(
            pk__in=[e.pk for e in employees],
        ).values_list("employee_number", flat=True)), {"30001", "30002"})
        self.assertEqual(set(EmployeeNumberHistory.objects.filter(
            department=target,
        ).values_list("employee_number", flat=True)), {"30001", "30002"})


# ==========================================
# 2. 判定と書き込みの間に割り込ませる順序固定試験
# ==========================================


class SQLiteSerializationOrderTests(SQLiteFileDatabaseTestCase):
    """先行を「判定済み・未確定」で止め、後続が待たされた後に最新状態で判定されることを確認する。

    Barrier だけでは実際に処理が重なったかを保証できないため、停止位置を固定する。
    DEFERRED に戻ると後続は待たずに database is locked で終了し、この試験は失敗する。
    """

    def test_admin_revocations_cannot_write_skew_below_two(self):
        first = self.create_admin("91002")
        second = self.create_admin("91003")

        def revoke(target):
            return lambda: change_business_admin_role(
                actor_id=self.manager.pk, employee_id=target.pk,
                grant=False, expected_role=True, reason="交代",
            )

        # 先行は人数確認（3人）を通過し、保存直前で停止する。
        first_result, second_result = self.run_first_then_second(
            revoke(first), revoke(second), pause_owner=EmployeeModel, pause_name="save",
        )
        self.assertNotIsInstance(first_result, Exception)
        self.assertIsInstance(second_result, RoleChangeError)
        self.assertIn("2人以上", str(second_result))
        self.assert_active_admin_count(2)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.ROLE_CHANGE).count(), 1)

    def test_employee_number_candidate_is_recomputed_after_waiting(self):
        department = Department.objects.create(name="開発部", code=3)
        url = reverse("management:employee_create")
        clients = [self.logged_in_client(), self.logged_in_client()]
        operation_ids = [uuid.uuid4(), uuid.uuid4()]

        def create(client, first_name, operation_id):
            return lambda: client.post(url, {
                "first_name": first_name, "last_name": "試験",
                "department_choice": str(department.pk), "hire_date": "2026-04-01",
                "operation_id": str(operation_id),
            })

        # 先行は 30001 を算出し、保全記録の予約位置で停止する。
        # （応答の context はスレッド間で混ざるため、結果は DB で確認する）
        first_response, second_response = self.run_first_then_second(
            create(clients[0], "太郎", operation_ids[0]),
            create(clients[1], "花子", operation_ids[1]),
            pause_owner=management_views, pause_name="reserve_pending",
        )
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        issued = dict(EmployeeNumberOperation.objects.values_list("operation_id", "issued_number"))
        self.assertEqual(issued, {operation_ids[0]: "30001", operation_ids[1]: "30002"})

    def test_refinalization_after_reopen_keeps_one_current_version(self):
        employee = self.create_employee()
        self.create_completed_session(employee)
        finalize_month(manager_id=self.manager.pk, employee_id=employee.pk,
                       target_month=TARGET_MONTH, checked_no_record=True)
        reopen_month(manager_id=self.manager.pk, employee_id=employee.pk,
                     target_month=TARGET_MONTH, reason="再確認")

        def finalize():
            return finalize_month(manager_id=self.manager.pk, employee_id=employee.pk,
                                  target_month=TARGET_MONTH, checked_no_record=True)

        # 確定解除後は既存行の更新になるため一意制約では守られない。直列化だけで守られることを確認する。
        first_result, second_result = self.run_first_then_second(
            finalize, finalize, pause_owner=management_services, pause_name="build_monthly_report",
        )
        self.assertIsInstance(first_result, MonthlyClosing)
        self.assertIsInstance(second_result, AdminActionError)
        closing = MonthlyClosing.objects.get(employee=employee, target_month=TARGET_MONTH)
        self.assertEqual(closing.status, MonthlyClosing.Status.FINALIZED)
        self.assertEqual(closing.version, 3)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.MONTH_FINALIZE).count(), 2)

    def test_finalization_waiting_for_approval_snapshots_approved_values(self):
        employee = self.create_employee()
        work = self.create_completed_session(employee)
        correction = self.create_pending_correction(employee, work)

        def approve():
            return review_correction(
                manager_id=self.manager.pk, correction_id=correction.pk, action="approve",
            )

        def finalize():
            return finalize_month(manager_id=self.manager.pk, employee_id=employee.pk,
                                  target_month=TARGET_MONTH, checked_no_record=True)

        # 承認を検証直後で止める。確定は承認の確定を待ち、承認後の勤務でスナップショットを作る。
        approve_result, finalize_result = self.run_first_then_second(
            approve, finalize, pause_owner=management_services, pause_name="validate_proposal",
        )
        self.assertNotIsInstance(approve_result, Exception)
        self.assertIsInstance(finalize_result, MonthlyClosing)
        work.refresh_from_db()
        self.assertEqual(work.version, 2)
        day = next(row for row in finalize_result.snapshot["daily"] if row["day"] == "2026-09-15")
        self.assertEqual(day["session_version"], 2)
        self.assertEqual(day["clock_out_at"], work.clock_out_at.isoformat())
        self.assertEqual(timezone.localtime(work.clock_out_at).time().isoformat(), "18:30:00")

    def test_clock_replay_waits_and_returns_recorded_event(self):
        employee = self.create_employee()
        today = timezone.localdate()
        operation_id = uuid.uuid4()

        def clock():
            return record_clock_action(
                employee_id=employee.pk, kind=ClockEvent.Kind.CLOCK_IN,
                operation_id=operation_id, expected_work_date=today,
            )

        # 先行は打刻を追加した後、確定前で停止する。
        first_result, second_result = self.run_first_then_second(
            clock, clock, pause_owner=attendance_services, pause_name="sync_incomplete_occurrences",
        )
        self.assertFalse(first_result.already_recorded)
        self.assertTrue(second_result.already_recorded)
        self.assertEqual(second_result.event.pk, first_result.event.pk)
        self.assertEqual(ClockEvent.objects.filter(operation_id=operation_id).count(), 1)

    def test_distinct_clock_in_waits_and_is_rejected_by_business_rule(self):
        employee = self.create_employee()
        today = timezone.localdate()

        def clock():
            return record_clock_action(
                employee_id=employee.pk, kind=ClockEvent.Kind.CLOCK_IN,
                operation_id=uuid.uuid4(), expected_work_date=today,
            )

        first_result, second_result = self.run_first_then_second(
            clock, clock, pause_owner=attendance_services, pause_name="sync_incomplete_occurrences",
        )
        self.assertFalse(first_result.already_recorded)
        self.assertIsInstance(second_result, ClockActionError)
        self.assertEqual(WorkSession.objects.filter(employee=employee).count(), 1)
        self.assertEqual(ClockEvent.objects.count(), 1)


# ==========================================
# 3. database is locked 発生時の整合性
# ==========================================


class SQLiteLockFailureIntegrityTests(SQLiteFileDatabaseTestCase):
    """別接続でロックを保持し、ロック待ちの上限を短くして database is locked を発生させる。

    write: 開始時（BEGIN IMMEDIATE）で失敗する。何も書き込まれていないことを確認する。
    read:  書き込み後の COMMIT で失敗する。途中の書き込みがすべて取り消されることを確認する。
    いずれもロック解除後に同じ操作IDで再送し、ちょうど1回だけ反映されることを確認する。
    """

    # ---- 打刻 ----

    def _assert_no_clock_rows(self, employee):
        self.assertFalse(WorkSession.objects.filter(employee=employee).exists())
        self.assertFalse(ClockEvent.objects.exists())
        self.assertFalse(IncompleteOccurrence.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.CLOCK).exists())

    def _assert_clock_retry_is_idempotent(self, employee, operation_id, today):
        def clock():
            return record_clock_action(
                employee_id=employee.pk, kind=ClockEvent.Kind.CLOCK_IN,
                operation_id=operation_id, expected_work_date=today,
            )
        self.assertFalse(clock().already_recorded)
        self.assertTrue(clock().already_recorded)
        self.assertEqual(ClockEvent.objects.filter(operation_id=operation_id).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.CLOCK).count(), 1)

    def test_clock_in_fails_cleanly_when_write_lock_is_held(self):
        employee = self.create_employee()
        today, operation_id = timezone.localdate(), uuid.uuid4()
        with self.locked("write"), self.assertRaisesMessage(OperationalError, "locked"):
            record_clock_action(
                employee_id=employee.pk, kind=ClockEvent.Kind.CLOCK_IN,
                operation_id=operation_id, expected_work_date=today,
            )
        self._assert_no_clock_rows(employee)
        self._assert_clock_retry_is_idempotent(employee, operation_id, today)

    def test_clock_in_rolls_back_when_commit_is_locked(self):
        employee = self.create_employee()
        today, operation_id = timezone.localdate(), uuid.uuid4()
        with self.locked("read"), self.assertRaisesMessage(OperationalError, "locked"):
            record_clock_action(
                employee_id=employee.pk, kind=ClockEvent.Kind.CLOCK_IN,
                operation_id=operation_id, expected_work_date=today,
            )
        self._assert_no_clock_rows(employee)
        self._assert_clock_retry_is_idempotent(employee, operation_id, today)

    def test_clock_view_reports_unconfirmed_result_on_lock(self):
        employee = self.create_employee()
        client = self.logged_in_client(employee)
        today = timezone.localdate()
        with self.locked("write"):
            response = client.post(reverse("attendance:clock_action"), {
                "action": ClockEvent.Kind.CLOCK_IN, "operation_id": str(uuid.uuid4()),
                "work_date": today.isoformat(), "session_id": "", "session_version": "",
            }, follow=True)
        self.assertContains(response, "保存処理の結果を確認できませんでした")
        self._assert_no_clock_rows(employee)

    # ---- 社員番号 ----

    def test_employee_create_rolls_back_and_releases_ledger_reservation(self):
        department = Department.objects.create(name="開発部", code=3)
        client = self.logged_in_client()
        operation_id = str(uuid.uuid4())
        data = {"first_name": "太郎", "last_name": "佐藤", "department_choice": str(department.pk),
                "hire_date": "2026-04-01", "operation_id": operation_id}
        with self.numbering_ledger_enabled() as path:
            with self.locked("read"):
                response = client.post(reverse("management:employee_create"), data)
            self.assertContains(response, "登録が競合しました")
            self.assertEqual(get_user_model().objects.count(), 1)
            self.assertFalse(EmploymentInfo.objects.exists())
            self.assertFalse(EmployeeNumberHistory.objects.exists())
            self.assertFalse(EmployeeNumberOperation.objects.exists())
            self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.EMPLOYEE_CREATE).exists())
            self.assert_ledger_has_no_pending(path)

            # 同じ操作IDの再送は1回だけ反映され、保全記録もDBと一致する。
            retry = client.post(reverse("management:employee_create"), data)
            self.assertEqual(retry.status_code, 200)
            self.assertEqual(retry.context["employee"].employee_number, "30001")
            replay = client.post(reverse("management:employee_create"), data)
            self.assertEqual(replay.status_code, 302)
            self.assertEqual(EmployeeNumberHistory.objects.count(), 1)
            self.assert_ledger_has_no_pending(path)

    def test_employee_transfer_rolls_back_number_on_locked_commit(self):
        source = Department.objects.create(name="旧部署", code=1)
        target = Department.objects.create(name="新部署", code=3)
        employee = self.create_employee(
            "10001", first_name="一郎", last_name="試験", department=source.name,
        )
        EmployeeNumberHistory.objects.create(
            employee=employee, department=source, employee_number=employee.employee_number,
        )
        client = self.logged_in_client()
        url = reverse("management:employee_edit", args=[employee.pk])
        data = {
            "employee_number": employee.employee_number, "first_name": "一郎", "last_name": "試験",
            "department_choice": str(target.pk), "is_active": "on", "change_reason": "異動",
            "edit_state": client.get(url).context["edit_state"], "operation_id": str(uuid.uuid4()),
        }
        with self.numbering_ledger_enabled() as path:
            with self.locked("read"):
                response = client.post(url, data)
            self.assertContains(response, "更新が競合しました")
            # 保存失敗の画面に、ロールバックされた新番号を表示しない（09章）。
            self.assertEqual(response.context["employee"].employee_number, "10001")
            self.assertNotContains(response, "30001")
            employee.refresh_from_db()
            self.assertEqual((employee.employee_number, employee.department), ("10001", "旧部署"))
            self.assertEqual(
                list(EmployeeNumberHistory.objects.values_list("employee_number", flat=True)),
                ["10001"],
            )
            self.assertFalse(EmployeeNumberOperation.objects.exists())
            self.assert_ledger_has_no_pending(path)

            retry = client.post(url, data)
            self.assertEqual(retry.status_code, 302)
            employee.refresh_from_db()
            self.assertEqual(employee.employee_number, "30001")
            self.assert_ledger_has_no_pending(path)

    def test_failed_ledger_release_keeps_numbering_stopped(self):
        """DB確定前の保留を解除できない場合は保留が残り、照合まで採番を止める（安全側）。"""
        with self.numbering_ledger_enabled() as path:
            operation_id = uuid.uuid4()
            reserve_pending(kind="department_create", value=3,
                            actor_id=self.manager.pk, operation_id=operation_id)
            # 保留中に別経路でDBが変わった状態。
            Department.objects.create(name="別経路", code=5)
            with self.assertRaises(NumberingLedgerError):
                cancel_pending(kind="department_create", operation_id=operation_id)
            self.assertEqual(read_snapshot(path)["pending"][0]["operation_id"], str(operation_id))
            with self.assertRaises(ValidationError):
                require_numbering_ready()

    # ---- 部署 ----

    def test_department_create_rolls_back_and_releases_ledger_reservation(self):
        client = self.logged_in_client()
        data = {"name": "営業部", "code": "3", "is_active": "on", "operation_id": str(uuid.uuid4())}
        url = reverse("management:department_create")
        with self.numbering_ledger_enabled() as path:
            with self.locked("read"):
                response = client.post(url, data)
            self.assertEqual(response.status_code, 409)
            self.assertFalse(Department.objects.exists())
            self.assertFalse(DepartmentRegistration.objects.exists())
            self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.DEPARTMENT_CREATE).exists())
            self.assert_ledger_has_no_pending(path)

            self.assertEqual(client.post(url, data).status_code, 302)
            self.assertEqual(client.post(url, data).status_code, 302)
            self.assertEqual(DepartmentRegistration.objects.count(), 1)
            self.assert_ledger_has_no_pending(path)

    # ---- 管理者2名以上 ----

    def test_role_revocation_on_lock_keeps_admin_unchanged(self):
        first = self.create_admin("91002")
        self.create_admin("91003")
        client = self.logged_in_client()
        with self.locked("write"):
            response = client.post(
                reverse("management:employee_role", args=[first.pk]),
                {"expected_role": "admin", "desired_role": "employee", "change_reason": "交代"},
            )
        self.assertContains(response, "同時更新のため変更できませんでした")
        self.assert_active_admin_count(3)
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.ROLE_CHANGE).exists())

    def test_admin_deactivation_rolls_back_on_locked_commit(self):
        department = Department.objects.create(name="総務部", code=1)
        self.create_admin("91002", department=department.name)
        target = self.create_admin("91003", department=department.name)
        client = self.logged_in_client()
        url = reverse("management:employee_edit", args=[target.pk])
        data = {
            "employee_number": target.employee_number, "first_name": "Test", "last_name": "Manager",
            "department_choice": str(department.pk), "change_reason": "退職",
            "edit_state": client.get(url).context["edit_state"], "operation_id": str(uuid.uuid4()),
        }
        with self.locked("read"):
            response = client.post(url, data)
        self.assertContains(response, "更新が競合しました")
        target.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assert_active_admin_count(3)
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.EMPLOYEE_UPDATE).exists())

    # ---- 月次確定 ----

    def test_month_finalization_fails_cleanly_when_write_lock_is_held(self):
        employee = self.create_employee()
        self.create_completed_session(employee)
        with self.locked("write"), self.assertRaisesMessage(OperationalError, "locked"):
            finalize_month(manager_id=self.manager.pk, employee_id=employee.pk,
                           target_month=TARGET_MONTH, checked_no_record=True)
        self.assertFalse(MonthlyClosing.objects.exists())
        self.assertFalse(Notification.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.MONTH_FINALIZE).exists())

    def test_refinalization_rolls_back_on_locked_commit(self):
        employee = self.create_employee()
        self.create_completed_session(employee)
        finalize_month(manager_id=self.manager.pk, employee_id=employee.pk,
                       target_month=TARGET_MONTH, checked_no_record=True)
        reopened = reopen_month(manager_id=self.manager.pk, employee_id=employee.pk,
                                target_month=TARGET_MONTH, reason="再確認")
        notifications = Notification.objects.count()
        with self.locked("read"), self.assertRaisesMessage(OperationalError, "locked"):
            finalize_month(manager_id=self.manager.pk, employee_id=employee.pk,
                           target_month=TARGET_MONTH, checked_no_record=True)
        closing = MonthlyClosing.objects.get(pk=reopened.pk)
        self.assertEqual((closing.status, closing.version), (reopened.status, reopened.version))
        self.assertEqual((closing.snapshot, closing.integrity_check_result), ({}, {}))
        self.assertIsNone(closing.finalized_by_id)
        self.assertEqual(Notification.objects.count(), notifications)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.MONTH_FINALIZE).count(), 1)

        finalize_month(manager_id=self.manager.pk, employee_id=employee.pk,
                       target_month=TARGET_MONTH, checked_no_record=True)
        closing.refresh_from_db()
        self.assertEqual(closing.version, reopened.version + 1)

    def test_month_reopen_on_lock_keeps_finalized_snapshot(self):
        employee = self.create_employee()
        self.create_completed_session(employee)
        finalized = finalize_month(manager_id=self.manager.pk, employee_id=employee.pk,
                                   target_month=TARGET_MONTH, checked_no_record=True)
        with self.locked("read"), self.assertRaisesMessage(OperationalError, "locked"):
            reopen_month(manager_id=self.manager.pk, employee_id=employee.pk,
                         target_month=TARGET_MONTH, reason="再確認")
        closing = MonthlyClosing.objects.get(pk=finalized.pk)
        self.assertEqual(closing.status, MonthlyClosing.Status.FINALIZED)
        self.assertEqual(closing.version, finalized.version)
        self.assertEqual(closing.snapshot, finalized.snapshot)
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.MONTH_REOPEN).exists())

    # ---- 修正申請の承認 ----

    def test_correction_approval_on_lock_keeps_request_pending(self):
        employee = self.create_employee()
        work = self.create_completed_session(employee)
        correction = self.create_pending_correction(employee, work)
        client = self.logged_in_client()
        with self.locked("read"):
            response = client.post(
                reverse("management:correction_review", args=[correction.pk]),
                {"action": "approve"}, follow=True,
            )
        self.assertContains(response, "審査を完了できませんでした")
        correction.refresh_from_db()
        work.refresh_from_db()
        self.assertEqual(correction.status, CorrectionRequest.Status.PENDING)
        self.assertEqual(work.version, 1)
        self.assertEqual(timezone.localtime(work.clock_out_at).hour, 18)
        self.assertEqual(timezone.localtime(work.clock_out_at).minute, 0)
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.CORRECTION_APPROVE).exists())


# ==========================================
# 4. ロック待ちの上限超過時の画面（11章：部分保存せず、成功と表示せず、結果確認を案内）
# ==========================================


class SQLiteLockFailureResponseTests(SQLiteFileDatabaseTestCase):
    """500 にせず、保存結果を確認できない旨を表示することを確認する。

    リダイレクト先の表示はロック解除後に取得する（表示側の処理をロックに巻き込まない）。
    """

    def assert_unconfirmed_message(self, client, response):
        self.assertEqual(response.status_code, 302)
        self.assertContains(client.get(response.url), UNCONFIRMED_SAVE_MESSAGE)

    def finalized_month(self):
        employee = self.create_employee()
        self.create_completed_session(employee)
        closing = finalize_month(manager_id=self.manager.pk, employee_id=employee.pk,
                                 target_month=TARGET_MONTH, checked_no_record=True)
        return employee, closing

    def test_month_finalize_view(self):
        employee = self.create_employee()
        self.create_completed_session(employee)
        client = self.logged_in_client()
        url = reverse("management:month_finalize", args=[employee.pk, 2026, 9])
        token = reconciliation_token(employee, TARGET_MONTH)
        with self.locked("write"):
            response = client.post(url, {"checked_no_record": "on", "reconciliation_token": token})
        self.assert_unconfirmed_message(client, response)
        self.assertFalse(MonthlyClosing.objects.exists())

    def test_month_reopen_view(self):
        employee, closing = self.finalized_month()
        client = self.logged_in_client()
        url = reverse("management:month_reopen", args=[employee.pk, 2026, 9])
        with self.locked("write"):
            response = client.post(url, {"reason": "再確認"})
        self.assert_unconfirmed_message(client, response)
        closing.refresh_from_db()
        self.assertEqual(closing.status, MonthlyClosing.Status.FINALIZED)

    def test_single_month_output_id_view(self):
        employee, _ = self.finalized_month()
        client = self.logged_in_client()
        with self.locked("write"):
            response = client.post(reverse("management:month_csv", args=[employee.pk, 2026, 9]))
        self.assert_unconfirmed_message(client, response)
        self.assertFalse(ExportBatch.objects.exists())

    def test_output_id_download_view(self):
        employee, _ = self.finalized_month()
        client = self.logged_in_client()
        client.post(reverse("management:month_csv", args=[employee.pk, 2026, 9]))
        batch = ExportBatch.objects.get()
        with self.locked("write"):
            response = client.post(reverse("management:batch_download", args=[batch.output_id, "daily"]))
        self.assertContains(response, UNCONFIRMED_SAVE_MESSAGE, status_code=503)
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.CSV_EXPORT).exists())

    def test_employment_edit_view_keeps_input(self):
        employee = self.create_employee()
        EmploymentInfo.objects.create(employee=employee, department="", hire_date=date(2026, 1, 1))
        client = self.logged_in_client()
        url = reverse("management:employment_edit", args=[employee.pk])
        with self.locked("read"):
            response = client.post(url, {"hire_date": "2025-12-01", "leave_date": "",
                                         "change_reason": "入社日の訂正"})
        self.assertContains(response, UNCONFIRMED_SAVE_MESSAGE)
        self.assertContains(response, "2025-12-01")
        employee.refresh_from_db()
        self.assertEqual(employee.hire_date, date(2026, 1, 1))
        self.assertEqual(EmploymentInfo.objects.get(employee=employee).hire_date, date(2026, 1, 1))

    def test_initial_password_reissue_does_not_show_password(self):
        employee = self.create_employee()
        client = self.logged_in_client()
        url = reverse("management:employee_password_reset", args=[employee.pk])
        ticket = client.get(url).context["ticket"]
        with self.locked("write"):
            response = client.post(url, {"confirm": "yes", "ticket": ticket})
        self.assertNotIn("initial_password", response.context or {})
        self.assert_unconfirmed_message(client, response)
        employee.refresh_from_db()
        self.assertTrue(employee.check_password(PASSWORD))
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.EMPLOYEE_UPDATE).exists())

    def test_password_change_view(self):
        employee = self.create_employee()
        client = self.logged_in_client(employee)
        new_password = "ChangedPassword_2026!"
        with self.locked("read"):
            response = client.post(reverse("accounts:password_change"), {
                "old_password": PASSWORD, "new_password1": new_password,
                "new_password2": new_password,
            })
        self.assertContains(response, UNCONFIRMED_SAVE_MESSAGE)
        employee.refresh_from_db()
        self.assertTrue(employee.check_password(PASSWORD))

    def test_mark_all_notifications_read_view(self):
        employee = self.create_employee()
        notification = create_notification(
            recipient=employee, kind=Notification.Kind.choices[0][0], title="確認", body="本文",
        )
        client = self.logged_in_client(employee)
        with self.locked("write"):
            response = client.post(reverse("notifications:read_all"))
        self.assert_unconfirmed_message(client, response)
        notification.refresh_from_db()
        self.assertIsNone(notification.read_at)
