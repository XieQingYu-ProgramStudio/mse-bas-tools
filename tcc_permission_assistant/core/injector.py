"""Generate and execute reviewed, parameterized TCC injection plans."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from tcc_permission_assistant.core.backup import BackupManager
from tcc_permission_assistant.core.errors import (
    InjectionConfirmationRequired,
    InjectionDatabaseError,
    InjectionError,
    InjectionSchemaError,
    UnsupportedInjectionScope,
    VerificationError,
)
from tcc_permission_assistant.core.models import (
    AccessSchema,
    BatchInjectionResult,
    InjectionOperation,
    InjectionPlan,
    InjectionResult,
    PermissionAction,
    PermissionStatus,
    TCCDatabaseScope,
    TCCRecord,
    TCCService,
    VerificationResult,
)
from tcc_permission_assistant.core.permission_map import (
    get_service_definition,
    resolve_service,
)
from tcc_permission_assistant.core.security import validate_bundle_id
from tcc_permission_assistant.core.tcc_db import TCCDatabase

CONFIRMATION_PHRASE = "INJECT"
INSERT_AUTH_REASON = 3
INSERT_AUTH_VERSION = 1
INSERT_CLIENT_TYPE = 0


@dataclass(frozen=True, slots=True)
class InjectionConfirmation:
    """Two explicit user confirmations required before any write."""

    applications_closed: bool
    phrase: str


def build_injection_plan(
    database: TCCDatabase,
    bundle_id: str,
    service: TCCService | str,
    action: PermissionAction | str,
    *,
    now_epoch: int | None = None,
    indirect_object_identifier: str | None = None,
) -> InjectionPlan:
    """Build an UPDATE, INSERT, or DELETE statement from the live schema."""

    _ensure_user_scope(database.scope)
    validated_bundle_id = validate_bundle_id(bundle_id)
    resolved_service = resolve_service(service)
    try:
        parsed_action = PermissionAction(action)
    except ValueError as exc:
        raise InjectionError(f"不支持的权限操作：{action}") from exc

    schema = database.read_access_schema()
    lookup = database.lookup_permissions(
        validated_bundle_id,
        [resolved_service],
    )[0]
    target_identifier = _resolve_indirect_object_identifier(
        resolved_service,
        lookup.records,
        indirect_object_identifier,
    )
    target_records = (
        tuple(
            record
            for record in lookup.records
            if str(record.indirect_object_identifier) == target_identifier
        )
        if target_identifier is not None
        else lookup.records
    )
    timestamp = int(time.time()) if now_epoch is None else int(now_epoch)

    if parsed_action is PermissionAction.DELETE:
        statement, parameters = _build_delete(
            validated_bundle_id,
            resolved_service,
            target_identifier,
        )
        operation = InjectionOperation.DELETE
    elif lookup.records:
        statement, parameters = _build_update(
            schema,
            validated_bundle_id,
            resolved_service,
            parsed_action,
            target_identifier,
        )
        operation = InjectionOperation.UPDATE
    else:
        statement, parameters = _build_insert(
            schema,
            validated_bundle_id,
            resolved_service,
            parsed_action,
            timestamp,
            target_identifier,
        )
        operation = InjectionOperation.INSERT

    return InjectionPlan(
        database_path=database.path,
        scope=database.scope,
        bundle_id=validated_bundle_id,
        service=resolved_service,
        action=parsed_action,
        operation=operation,
        current_status=_status_from_records(target_records),
        existing_record_count=len(target_records),
        statement=statement,
        parameters=tuple(parameters),
        literal_sql=render_literal_sql(statement, parameters),
        reset_command=(
            "tccutil reset "
            f"{get_service_definition(resolved_service).cli_name} "
            f"{validated_bundle_id}"
        ),
        generated_at_epoch=timestamp,
        indirect_object_identifier=target_identifier,
    )


def execute_dynamic_injection(
    plan: InjectionPlan,
    *,
    backup_manager: BackupManager | None = None,
) -> InjectionResult:
    """Execute one GUI toggle immediately while preserving backup and verification."""

    _ensure_user_scope(plan.scope)
    validated_plan = _validate_plan_for_execution(plan)
    manager = backup_manager or BackupManager()
    backup = manager.create_backup(
        validated_plan.database_path,
        TCCDatabaseScope.USER,
    )
    rows_changed = _execute_write(validated_plan, backup.path)
    verifications, rolled_back, rollback_error = _verify_and_rollback(
        (validated_plan,),
        backup.path,
    )
    verification = verifications[0]
    return InjectionResult(
        plan=validated_plan,
        backup=backup,
        rows_changed=rows_changed,
        verification=verification,
        rolled_back=rolled_back,
        rollback_error=rollback_error,
    )


def execute_injection(
    plan: InjectionPlan,
    confirmation: InjectionConfirmation,
    *,
    backup_manager: BackupManager | None = None,
) -> InjectionResult:
    """Backup, write in one transaction, commit, and verify."""

    _ensure_user_scope(plan.scope)
    if not confirmation.applications_closed:
        raise InjectionConfirmationRequired("必须确认相关应用已经完全退出。")
    if confirmation.phrase.strip() != CONFIRMATION_PHRASE:
        raise InjectionConfirmationRequired(
            f"必须输入 {CONFIRMATION_PHRASE} 才能执行写入。"
        )

    validated_plan = _validate_plan_for_execution(plan)
    manager = backup_manager or BackupManager()
    backup = manager.create_backup(
        validated_plan.database_path,
        TCCDatabaseScope.USER,
    )
    rows_changed = _execute_write(validated_plan, backup.path)
    verifications, rolled_back, rollback_error = _verify_and_rollback(
        (validated_plan,),
        backup.path,
    )
    verification = verifications[0]
    return InjectionResult(
        plan=validated_plan,
        backup=backup,
        rows_changed=rows_changed,
        verification=verification,
        rolled_back=rolled_back,
        rollback_error=rollback_error,
    )


def execute_batch_injection(
    plans: tuple[InjectionPlan, ...] | list[InjectionPlan],
    confirmation: InjectionConfirmation,
    *,
    backup_manager: BackupManager | None = None,
) -> BatchInjectionResult:
    """Backup once and execute all plans atomically in one transaction."""

    if not plans:
        raise InjectionError("批量计划为空。")
    if not confirmation.applications_closed:
        raise InjectionConfirmationRequired("必须确认相关应用已经完全退出。")
    if confirmation.phrase.strip() != CONFIRMATION_PHRASE:
        raise InjectionConfirmationRequired(
            f"必须输入 {CONFIRMATION_PHRASE} 才能执行写入。"
        )
    database_path, validated_plans = _validate_batch_plans(plans)
    manager = backup_manager or BackupManager()
    backup = manager.create_backup(database_path, TCCDatabaseScope.USER)
    rows_changed = _execute_batch_write(validated_plans, backup.path)
    verifications, rolled_back, rollback_error = _verify_and_rollback(
        validated_plans,
        backup.path,
    )
    return BatchInjectionResult(
        plans=validated_plans,
        backup=backup,
        rows_changed=rows_changed,
        verifications=verifications,
        rolled_back=rolled_back,
        rollback_error=rollback_error,
    )


def execute_dynamic_batch_injection(
    plans: tuple[InjectionPlan, ...] | list[InjectionPlan],
    *,
    backup_manager: BackupManager | None = None,
) -> BatchInjectionResult:
    """Execute a GUI-initiated batch immediately with backup and rollback."""

    database_path, validated_plans = _validate_batch_plans(plans)
    manager = backup_manager or BackupManager()
    backup = manager.create_backup(database_path, TCCDatabaseScope.USER)
    rows_changed = _execute_batch_write(validated_plans, backup.path)
    verifications, rolled_back, rollback_error = _verify_and_rollback(
        validated_plans,
        backup.path,
    )
    return BatchInjectionResult(
        plans=validated_plans,
        backup=backup,
        rows_changed=rows_changed,
        verifications=verifications,
        rolled_back=rolled_back,
        rollback_error=rollback_error,
    )


def _validate_batch_plans(
    plans: tuple[InjectionPlan, ...] | list[InjectionPlan],
) -> tuple[Path, tuple[InjectionPlan, ...]]:
    if not plans:
        raise InjectionError("批量计划为空。")
    first = plans[0]
    _ensure_user_scope(first.scope)
    database_path = first.database_path
    seen: set[tuple[str, TCCService]] = set()
    for plan in plans:
        _ensure_user_scope(plan.scope)
        if plan.database_path != database_path:
            raise InjectionError("批量计划包含不同的目标数据库。")
        key = (plan.bundle_id, plan.service)
        if key in seen:
            raise InjectionError(
                f"批量计划包含重复权限：{plan.bundle_id} / {plan.service.value}"
            )
        seen.add(key)

    validated_plans = tuple(_validate_plan_for_execution(plan) for plan in plans)
    return database_path, validated_plans


def _execute_write(plan: InjectionPlan, backup_path: Path) -> int:
    connection: sqlite3.Connection | None = None
    rows_changed = 0
    try:
        connection = sqlite3.connect(
            f"{plan.database_path.as_uri()}?mode=rw",
            uri=True,
            timeout=2.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA busy_timeout = 2000")
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(plan.statement, plan.parameters)
        rows_changed = max(cursor.rowcount, 0)
        connection.commit()
        return rows_changed
    except sqlite3.Error as exc:
        if connection is not None and connection.in_transaction:
            connection.rollback()
        raise InjectionDatabaseError(
            f"写入 TCC 数据库失败：{exc}。事务未提交；备份位于：{backup_path}"
        ) from exc
    finally:
        if connection is not None:
            connection.close()


def _execute_batch_write(
    plans: tuple[InjectionPlan, ...],
    backup_path: Path,
) -> int:
    connection: sqlite3.Connection | None = None
    rows_changed = 0
    try:
        database_path = plans[0].database_path
        connection = sqlite3.connect(
            f"{database_path.as_uri()}?mode=rw",
            uri=True,
            timeout=2.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA busy_timeout = 2000")
        connection.execute("BEGIN IMMEDIATE")
        for plan in plans:
            cursor = connection.execute(plan.statement, plan.parameters)
            rows_changed += max(cursor.rowcount, 0)
        connection.commit()
        return rows_changed
    except sqlite3.Error as exc:
        if connection is not None and connection.in_transaction:
            connection.rollback()
        raise InjectionDatabaseError(
            f"批量写入 TCC 数据库失败：{exc}。事务已回滚；备份位于：{backup_path}"
        ) from exc
    finally:
        if connection is not None:
            connection.close()


def _verify_and_rollback(
    plans: tuple[InjectionPlan, ...],
    backup_path: Path,
) -> tuple[tuple[VerificationResult, ...], bool, str | None]:
    verifications: list[VerificationResult] = []
    try:
        for plan in plans:
            verifications.append(_verify_plan(plan, backup_path))
    except VerificationError as exc:
        rollback_error = _rollback_database(backup_path, plans[0].database_path)
        if rollback_error is None:
            raise VerificationError(f"{exc} 已自动回滚到备份。") from exc
        raise VerificationError(
            f"{exc} 自动回滚失败：{rollback_error}。请手动恢复备份：{backup_path}"
        ) from exc

    if verifications and all(result.success for result in verifications):
        return tuple(verifications), False, None

    rollback_error = _rollback_database(backup_path, plans[0].database_path)
    return tuple(verifications), rollback_error is None, rollback_error


def _rollback_database(backup_path: Path, database_path: Path) -> str | None:
    source: sqlite3.Connection | None = None
    target: sqlite3.Connection | None = None
    try:
        source = sqlite3.connect(
            f"{backup_path.as_uri()}?mode=ro",
            uri=True,
            timeout=2.0,
        )
        source.execute("PRAGMA busy_timeout = 2000")
        source.execute("PRAGMA query_only = ON")
        target = sqlite3.connect(
            f"{database_path.as_uri()}?mode=rw",
            uri=True,
            timeout=2.0,
            isolation_level=None,
        )
        target.execute("PRAGMA busy_timeout = 2000")
        source.backup(target)
        check = target.execute("PRAGMA quick_check").fetchone()
        if check is None or str(check[0]).casefold() != "ok":
            return "回滚数据库完整性检查失败。"
        return None
    except sqlite3.Error as exc:
        return str(exc)
    finally:
        if target is not None:
            target.close()
        if source is not None:
            source.close()


def _verify_plan(plan: InjectionPlan, backup_path: Path) -> VerificationResult:
    if plan.action is PermissionAction.ALLOW:
        expected = PermissionStatus.ALLOWED
    elif plan.action is PermissionAction.DENY:
        expected = PermissionStatus.DENIED
    else:
        expected = PermissionStatus.NO_RECORD
    try:
        lookup = TCCDatabase(plan.database_path).lookup_permissions(
            plan.bundle_id,
            [plan.service],
        )[0]
    except Exception as exc:
        raise VerificationError(
            f"写入后验证失败：{exc}。备份位于：{backup_path}"
        ) from exc
    records = (
        tuple(
            record
            for record in lookup.records
            if str(record.indirect_object_identifier) == plan.indirect_object_identifier
        )
        if plan.indirect_object_identifier is not None
        else lookup.records
    )
    actual = _status_from_records(records)
    return VerificationResult(
        success=actual is expected,
        expected_status=expected,
        actual_status=actual,
        records=records,
    )


def _validate_plan_for_execution(plan: InjectionPlan) -> InjectionPlan:
    database = TCCDatabase(plan.database_path, scope=TCCDatabaseScope.USER)
    regenerated = build_injection_plan(
        database,
        plan.bundle_id,
        plan.service,
        plan.action,
        now_epoch=plan.generated_at_epoch,
        indirect_object_identifier=plan.indirect_object_identifier,
    )
    if regenerated != plan:
        raise InjectionError(
            "注入计划已过期或与当前数据库状态不一致，请重新读取后再操作。"
        )
    return regenerated


def _build_update(
    schema: AccessSchema,
    bundle_id: str,
    service: TCCService,
    action: PermissionAction,
    indirect_object_identifier: str | None,
) -> tuple[str, list[object]]:
    assignments = ["auth_value = ?"]
    parameters: list[object] = [action.auth_value]
    if schema.has_column("auth_reason"):
        assignments.append("auth_reason = ?")
        parameters.append(INSERT_AUTH_REASON)
    if schema.has_column("auth_version"):
        assignments.append("auth_version = ?")
        parameters.append(INSERT_AUTH_VERSION)
    parameters.extend((bundle_id, service.value))
    statement = (
        f"UPDATE access SET {', '.join(assignments)} WHERE client = ? AND service = ?"
    )
    if indirect_object_identifier is not None:
        statement += " AND indirect_object_identifier = ?"
        parameters.append(indirect_object_identifier)
    return statement, parameters


def _build_delete(
    bundle_id: str,
    service: TCCService,
    indirect_object_identifier: str | None,
) -> tuple[str, list[object]]:
    statement = "DELETE FROM access WHERE client = ? AND service = ?"
    parameters: list[object] = [bundle_id, service.value]
    if indirect_object_identifier is not None:
        statement += " AND indirect_object_identifier = ?"
        parameters.append(indirect_object_identifier)
    return statement, parameters


def _build_insert(
    schema: AccessSchema,
    bundle_id: str,
    service: TCCService,
    action: PermissionAction,
    timestamp: int,
    indirect_object_identifier: str | None,
) -> tuple[str, list[object]]:
    values: dict[str, object] = {
        "service": service.value,
        "client": bundle_id,
        "auth_value": action.auth_value,
    }
    if schema.has_column("auth_reason"):
        values["auth_reason"] = INSERT_AUTH_REASON
    if schema.has_column("auth_version"):
        values["auth_version"] = INSERT_AUTH_VERSION
    if schema.has_column("client_type"):
        values["client_type"] = INSERT_CLIENT_TYPE
    if schema.has_column("indirect_object_identifier") and (
        indirect_object_identifier is not None
    ):
        values["indirect_object_identifier"] = indirect_object_identifier

    fallbacks: dict[str, object] = {
        "indirect_object_identifier": "UNUSED",
        "indirect_object_identifier_type": 0,
        "boot_uuid": "UNUSED",
        "last_modified": timestamp,
        "last_reminded": timestamp,
        "flags": 0,
    }
    for column in schema.columns:
        if (
            column.name not in values
            and column.not_null
            and column.default_value is None
            and column.name in fallbacks
        ):
            values[column.name] = fallbacks[column.name]

    uncovered = [
        column.name
        for column in schema.columns
        if column.not_null
        and column.default_value is None
        and column.name not in values
    ]
    if uncovered:
        raise InjectionSchemaError(
            "access 表存在无法安全填充的必填字段：" + ", ".join(uncovered)
        )

    columns = list(values)
    placeholders = ", ".join("?" for _ in columns)
    statement = f"INSERT INTO access ({', '.join(columns)}) VALUES ({placeholders})"
    return statement, list(values.values())


def _resolve_indirect_object_identifier(
    service: TCCService,
    records: Sequence[TCCRecord],
    explicit: str | None,
) -> str | None:
    if service is not TCCService.APPLE_EVENTS:
        return None
    if explicit is not None:
        value = explicit.strip()
        if not value:
            raise InjectionError("Apple Events 目标标识不能为空。")
        return value
    targets = {
        str(record.indirect_object_identifier)
        for record in records
        if record.indirect_object_identifier not in (None, "", "UNUSED")
    }
    if len(targets) == 1:
        return targets.pop()
    if len(targets) > 1:
        raise InjectionError(
            "该应用存在多个 Apple Events 目标，必须逐项指定 indirect object。"
        )
    raise InjectionError(
        "Apple Events 权限必须指定目标应用，不能在通用开关中批量处理。"
    )


def _status_from_records(records: Sequence[TCCRecord]) -> PermissionStatus:
    if not records:
        return PermissionStatus.NO_RECORD
    statuses = {record.status for record in records}
    return next(iter(statuses)) if len(statuses) == 1 else PermissionStatus.UNKNOWN


def render_literal_sql(
    statement: str,
    parameters: tuple[object, ...] | list[object],
) -> str:
    """Render parameterized SQL for review; execution still uses bindings."""

    parts = statement.split("?")
    if len(parts) != len(parameters) + 1:
        raise InjectionError("SQL 占位符数量与参数数量不一致。")
    rendered: list[str] = []
    for index, part in enumerate(parts):
        rendered.append(part)
        if index < len(parameters):
            rendered.append(_quote_sqlite_literal(parameters[index]))
    return "".join(rendered)


def _quote_sqlite_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, bytes):
        return f"X'{value.hex()}'"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise InjectionError(f"无法渲染 SQL 参数类型：{type(value).__name__}")


def _ensure_user_scope(scope: TCCDatabaseScope) -> None:
    if scope is not TCCDatabaseScope.USER:
        raise UnsupportedInjectionScope("阶段 3 仅允许写入用户级 TCC 数据库。")
