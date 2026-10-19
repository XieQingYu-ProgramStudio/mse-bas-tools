"""Generate and execute reviewed, parameterized TCC injection plans."""

from __future__ import annotations

import sqlite3
import time
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
    timestamp = int(time.time()) if now_epoch is None else int(now_epoch)

    if parsed_action is PermissionAction.DELETE:
        statement, parameters = _build_delete(
            validated_bundle_id,
            resolved_service,
        )
        operation = InjectionOperation.DELETE
    elif lookup.records:
        statement, parameters = _build_update(
            schema,
            validated_bundle_id,
            resolved_service,
            parsed_action,
        )
        operation = InjectionOperation.UPDATE
    else:
        statement, parameters = _build_insert(
            schema,
            validated_bundle_id,
            resolved_service,
            parsed_action,
            timestamp,
        )
        operation = InjectionOperation.INSERT

    return InjectionPlan(
        database_path=database.path,
        scope=database.scope,
        bundle_id=validated_bundle_id,
        service=resolved_service,
        action=parsed_action,
        operation=operation,
        current_status=lookup.status,
        existing_record_count=len(lookup.records),
        statement=statement,
        parameters=tuple(parameters),
        literal_sql=render_literal_sql(statement, parameters),
        reset_command=(
            "tccutil reset "
            f"{get_service_definition(resolved_service).cli_name} "
            f"{validated_bundle_id}"
        ),
        generated_at_epoch=timestamp,
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
    verification = _verify_plan(validated_plan, backup.path)
    return InjectionResult(
        plan=validated_plan,
        backup=backup,
        rows_changed=rows_changed,
        verification=verification,
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
    verification = _verify_plan(validated_plan, backup.path)
    return InjectionResult(
        plan=validated_plan,
        backup=backup,
        rows_changed=rows_changed,
        verification=verification,
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
    manager = backup_manager or BackupManager()
    backup = manager.create_backup(database_path, TCCDatabaseScope.USER)
    rows_changed = _execute_batch_write(validated_plans, backup.path)
    verifications = tuple(_verify_plan(plan, backup.path) for plan in validated_plans)
    return BatchInjectionResult(
        plans=validated_plans,
        backup=backup,
        rows_changed=rows_changed,
        verifications=verifications,
    )


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
    return VerificationResult(
        success=lookup.status is expected,
        expected_status=expected,
        actual_status=lookup.status,
        records=lookup.records,
    )


def _validate_plan_for_execution(plan: InjectionPlan) -> InjectionPlan:
    database = TCCDatabase(plan.database_path, scope=TCCDatabaseScope.USER)
    regenerated = build_injection_plan(
        database,
        plan.bundle_id,
        plan.service,
        plan.action,
        now_epoch=plan.generated_at_epoch,
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
    return statement, parameters


def _build_delete(
    bundle_id: str,
    service: TCCService,
) -> tuple[str, list[object]]:
    return (
        "DELETE FROM access WHERE client = ? AND service = ?",
        [bundle_id, service.value],
    )


def _build_insert(
    schema: AccessSchema,
    bundle_id: str,
    service: TCCService,
    action: PermissionAction,
    timestamp: int,
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
