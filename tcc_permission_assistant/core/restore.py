"""Reviewed TCC database restore from managed backups."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tcc_permission_assistant.core.backup import BackupManager
from tcc_permission_assistant.core.errors import (
    RestoreConfirmationRequired,
    RestoreError,
    RestoreSourceError,
    RestoreVerificationError,
    TCCAssistantError,
)
from tcc_permission_assistant.core.models import (
    RestorePlan,
    RestoreResult,
    TCCDatabaseScope,
)
from tcc_permission_assistant.core.tcc_db import TCCDatabase, tcc_database_path

USER_RESTORE_PHRASE = "RESTORE"
SYSTEM_RESTORE_PHRASE = "YES"

_ELEVATED_RESTORE_SCRIPT = """
on run argv
    set sourceFile to item 1 of argv
    set targetFile to item 2 of argv
    set restoreCommand to ".restore " & quoted form of sourceFile
    do shell script "/usr/bin/sqlite3 " & quoted form of targetFile & " " & quoted form of restoreCommand with administrator privileges
end run
""".strip()


@dataclass(frozen=True, slots=True)
class RestoreConfirmation:
    """Confirmation state required before replacing TCC data."""

    applications_closed: bool
    phrase: str


@dataclass(frozen=True, slots=True)
class RestoreCommandResult:
    """Captured result from the privileged osascript command."""

    returncode: int
    stdout: str
    stderr: str


class SystemRestoreRunner(Protocol):
    def restore(self, source: Path, target: Path) -> RestoreCommandResult:
        """Restore source into target with administrator privileges."""


class OsaScriptRestoreRunner:
    """Use a fixed AppleScript with path arguments, never a concatenated shell."""

    def __init__(self, timeout_seconds: float = 300.0) -> None:
        self._timeout_seconds = timeout_seconds

    def restore(self, source: Path, target: Path) -> RestoreCommandResult:
        try:
            completed = subprocess.run(
                [
                    "/usr/bin/osascript",
                    "-e",
                    _ELEVATED_RESTORE_SCRIPT,
                    str(source),
                    str(target),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise RestoreError("找不到 osascript，无法请求管理员授权。") from exc
        except subprocess.TimeoutExpired as exc:
            raise RestoreError("管理员授权或系统级恢复操作超时。") from exc
        return RestoreCommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


def build_restore_plan(
    backup_path: str | Path,
    scope: TCCDatabaseScope | str = TCCDatabaseScope.USER,
    *,
    backup_manager: BackupManager | None = None,
) -> RestorePlan:
    """Validate a managed backup and show where it will be restored."""

    parsed_scope = TCCDatabaseScope(scope)
    manager = backup_manager or BackupManager()
    candidate = Path(backup_path).expanduser()
    if not manager.is_managed_backup(candidate, parsed_scope):
        raise RestoreSourceError("恢复来源必须是本工具管理目录中的 .bak 文件。")
    try:
        inspection = TCCDatabase(candidate).inspect()
    except TCCAssistantError as exc:
        raise RestoreSourceError(f"备份文件不是有效的 TCC 数据库：{exc}") from exc

    target_path = tcc_database_path(parsed_scope)
    if candidate.resolve() == target_path.resolve():
        raise RestoreSourceError("备份文件不能与目标数据库是同一个文件。")
    return RestorePlan(
        backup_path=candidate.resolve(),
        target_path=target_path,
        scope=parsed_scope,
        current_database_exists=target_path.is_file(),
        source_access_row_count=inspection.access_row_count,
    )


def execute_restore(
    plan: RestorePlan,
    confirmation: RestoreConfirmation,
    *,
    backup_manager: BackupManager | None = None,
    system_runner: SystemRestoreRunner | None = None,
) -> RestoreResult:
    """Backup the current database, restore, then verify the access schema."""

    if not confirmation.applications_closed:
        raise RestoreConfirmationRequired("必须确认相关应用已经完全退出。")
    expected_phrase = (
        SYSTEM_RESTORE_PHRASE
        if plan.scope is TCCDatabaseScope.SYSTEM
        else USER_RESTORE_PHRASE
    )
    if confirmation.phrase.strip() != expected_phrase:
        raise RestoreConfirmationRequired(
            f"恢复确认短语不正确，必须输入 {expected_phrase}。"
        )

    manager = backup_manager or BackupManager()
    validated_plan = build_restore_plan(
        plan.backup_path,
        plan.scope,
        backup_manager=manager,
    )
    if validated_plan != plan:
        raise RestoreSourceError("恢复计划已过期或与当前状态不一致，请重新生成。")

    pre_restore_backup = None
    external_returncode = None
    if plan.current_database_exists:
        pre_restore_backup = manager.create_backup(
            plan.target_path,
            plan.scope,
        )

    try:
        if plan.scope is TCCDatabaseScope.USER:
            _restore_user_database(plan.backup_path, plan.target_path)
        else:
            runner = system_runner or OsaScriptRestoreRunner()
            result = runner.restore(plan.backup_path, plan.target_path)
            external_returncode = result.returncode
            if result.returncode != 0:
                raise RestoreError(
                    _restore_failure_message(result)
                    + _backup_suffix(pre_restore_backup)
                )
        inspection = TCCDatabase(plan.target_path, plan.scope).inspect()
        if inspection.access_row_count != plan.source_access_row_count:
            raise RestoreVerificationError(
                "恢复后的 access 记录数与备份不一致"
                f"（备份 {plan.source_access_row_count}，"
                f"实际 {inspection.access_row_count}）"
            )
    except RestoreVerificationError as exc:
        if plan.scope is TCCDatabaseScope.USER and pre_restore_backup is not None:
            try:
                _restore_user_database(
                    pre_restore_backup.path,
                    plan.target_path,
                )
            except (RestoreError, OSError, sqlite3.Error) as rollback_exc:
                raise RestoreVerificationError(
                    f"{exc}。自动回滚失败：{rollback_exc}。"
                    f"备份位于：{pre_restore_backup.path}"
                ) from exc
            raise RestoreVerificationError(
                f"{exc}。已自动回滚到恢复前备份：{pre_restore_backup.path}"
            ) from exc
        raise
    except RestoreError:
        raise
    except TCCAssistantError as exc:
        verification_error = RestoreVerificationError(
            f"恢复后验证失败：{exc}{_backup_suffix(pre_restore_backup)}"
        )
        if plan.scope is TCCDatabaseScope.USER and pre_restore_backup is not None:
            try:
                _restore_user_database(
                    pre_restore_backup.path,
                    plan.target_path,
                )
            except (RestoreError, OSError, sqlite3.Error) as rollback_exc:
                raise RestoreVerificationError(
                    f"{verification_error}。自动回滚失败：{rollback_exc}"
                ) from exc
            raise RestoreVerificationError(
                f"{verification_error}。已自动回滚到恢复前备份。"
            ) from exc
        raise verification_error from exc
    except (OSError, sqlite3.Error) as exc:
        raise RestoreError(
            f"恢复 TCC 数据库失败：{exc}{_backup_suffix(pre_restore_backup)}"
        ) from exc

    return RestoreResult(
        plan=plan,
        pre_restore_backup=pre_restore_backup,
        verified=True,
        access_row_count=inspection.access_row_count,
        schema_column_count=len(inspection.schema.columns),
        external_returncode=external_returncode,
    )


def _restore_user_database(source_path: Path, target_path: Path) -> None:
    if not target_path.parent.is_dir():
        raise RestoreError(f"目标数据库目录不存在：{target_path.parent}")
    source: sqlite3.Connection | None = None
    target: sqlite3.Connection | None = None
    temporary_path: Path | None = None
    try:
        source = sqlite3.connect(
            f"{source_path.as_uri()}?mode=ro",
            uri=True,
            timeout=2.0,
        )
        source.execute("PRAGMA query_only = ON")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".TCC-restore-",
            suffix=".db",
            dir=target_path.parent,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        target = sqlite3.connect(temporary_path, timeout=2.0)
        target.execute("PRAGMA busy_timeout = 2000")
        source.backup(target)
        check = target.execute("PRAGMA quick_check").fetchone()
        if check is None or str(check[0]).casefold() != "ok":
            raise RestoreVerificationError("恢复后的数据库完整性检查失败。")
        target.commit()
        target.close()
        target = None
        if target_path.exists():
            os.chmod(temporary_path, target_path.stat().st_mode & 0o777)
        else:
            os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, target_path)
        temporary_path = None
    except (sqlite3.Error, OSError):
        if target is not None and target.in_transaction:
            target.rollback()
        raise
    finally:
        if target is not None:
            target.close()
        if source is not None:
            source.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _restore_failure_message(result: RestoreCommandResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip()
    if not detail:
        detail = f"osascript 返回码 {result.returncode}"
    return f"系统级恢复失败：{detail}"


def _backup_suffix(backup) -> str:
    if backup is None:
        return "。"
    return f"。恢复前备份位于：{backup.path}"
