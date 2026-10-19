"""macOS, AMFI, and TCC database diagnostics with report export."""

from __future__ import annotations

import json
import os
import platform
import shlex
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from tcc_permission_assistant.branding import APP_NAME, PERMISSION_MODULE_NAME
from tcc_permission_assistant.core.errors import TCCAssistantError
from tcc_permission_assistant.core.models import (
    AccessColumn,
    TCCDatabaseScope,
)
from tcc_permission_assistant.core.tcc_db import TCCDatabase, tcc_database_path


class SIPState(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNKNOWN = "unknown"
    ERROR = "error"


class BootArgsState(str, Enum):
    PRESENT = "present"
    NOT_SET = "not_set"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Captured result of a diagnostic command."""

    returncode: int | None
    stdout: str
    stderr: str
    error: str | None = None


class DiagnosticRunner(Protocol):
    def run(self, command: Sequence[str]) -> ProcessResult:
        """Run one command with an argument list and capture text."""


class SubprocessDiagnosticRunner:
    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, command: Sequence[str]) -> ProcessResult:
        try:
            completed = subprocess.run(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError:
            return ProcessResult(None, "", "", f"找不到命令：{command[0]}")
        except subprocess.TimeoutExpired:
            return ProcessResult(None, "", "", f"命令执行超时：{command[0]}")
        except OSError as exc:
            return ProcessResult(None, "", "", str(exc))
        return ProcessResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


@dataclass(frozen=True, slots=True)
class CommandExecution:
    label: str
    command: tuple[str, ...]
    returncode: int | None
    completed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "command": list(self.command),
            "returncode": self.returncode,
            "completed": self.completed,
        }


@dataclass(frozen=True, slots=True)
class SIPDiagnostic:
    state: SIPState
    summary: str
    details: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "summary": self.summary,
            "details": list(self.details),
        }


@dataclass(frozen=True, slots=True)
class BootArgsDiagnostic:
    state: BootArgsState
    raw_value: str
    arguments: tuple[str, ...]
    detected_flags: tuple[str, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "raw_value": self.raw_value,
            "arguments": list(self.arguments),
            "detected_flags": list(self.detected_flags),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class DatabaseDiagnostic:
    path: Path
    scope: TCCDatabaseScope
    exists: bool
    posix_readable: bool
    posix_writable: bool
    schema_readable: bool
    access_row_count: int | None
    schema_columns: tuple[AccessColumn, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "scope": self.scope.value,
            "exists": self.exists,
            "posix_readable": self.posix_readable,
            "posix_writable": self.posix_writable,
            "schema_readable": self.schema_readable,
            "access_row_count": self.access_row_count,
            "schema_columns": [column.to_dict() for column in self.schema_columns],
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    generated_at: str
    macos_version: str
    macos_build: str | None
    advanced: bool
    sip: SIPDiagnostic
    boot_args: BootArgsDiagnostic
    amfipass_detected: bool
    amfipass_locations: tuple[Path, ...]
    user_database: DatabaseDiagnostic
    system_database: DatabaseDiagnostic
    likely_missing_full_disk_access: bool
    warnings: tuple[str, ...]
    commands: tuple[CommandExecution, ...]
    error_explanations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "macos": {
                "version": self.macos_version,
                "build": self.macos_build,
            },
            "advanced": self.advanced,
            "sip": self.sip.to_dict(),
            "boot_args": self.boot_args.to_dict(),
            "amfi": {
                "amfipass_detected": self.amfipass_detected,
                "amfipass_locations": [str(path) for path in self.amfipass_locations],
            },
            "databases": {
                "user": self.user_database.to_dict(),
                "system": self.system_database.to_dict(),
            },
            "likely_missing_full_disk_access": (self.likely_missing_full_disk_access),
            "warnings": list(self.warnings),
            "commands": [command.to_dict() for command in self.commands],
            "error_explanations": list(self.error_explanations),
        }

    def to_markdown(self) -> str:
        return render_markdown(self)


class DiagnosticsCollector:
    """Collect non-destructive TCC environment diagnostics."""

    BOOT_ARG_MARKERS = (
        "amfi=0x80",
        "amfi_get_out_of_my_way=0x1",
        "-amfipassbeta",
        "ipc_control_port_options=0",
    )
    DEFAULT_AMFIPASS_PATHS = (
        Path("/Library/Extensions/AMFIPass.kext"),
        Path("/System/Library/Extensions/AMFIPass.kext"),
    )

    def __init__(
        self,
        runner: DiagnosticRunner | None = None,
        *,
        user_database_path: str | Path | None = None,
        system_database_path: str | Path | None = None,
        amfipass_paths: Sequence[Path] | None = None,
        now: datetime | None = None,
    ) -> None:
        self._runner = runner or SubprocessDiagnosticRunner()
        self._user_database_path = Path(
            user_database_path or tcc_database_path(TCCDatabaseScope.USER)
        )
        self._system_database_path = Path(
            system_database_path or tcc_database_path(TCCDatabaseScope.SYSTEM)
        )
        self._amfipass_paths = tuple(amfipass_paths or self.DEFAULT_AMFIPASS_PATHS)
        self._now = now

    def collect(self, *, advanced: bool = False) -> DiagnosticReport:
        build_result = self._runner.run(["/usr/bin/sw_vers", "-buildVersion"])
        sip_result = self._runner.run(["/usr/bin/csrutil", "status"])
        boot_result = self._runner.run(["/usr/sbin/nvram", "boot-args"])

        sip = parse_sip_result(sip_result)
        boot_args = parse_boot_args_result(boot_result)
        amfipass_locations = tuple(
            path for path in self._amfipass_paths if path.exists()
        )
        amfipass_detected = bool(amfipass_locations) or (
            "-amfipassbeta" in boot_args.detected_flags
        )
        user_database = self._inspect_database(
            self._user_database_path,
            TCCDatabaseScope.USER,
            should_inspect=True,
        )
        system_database = self._inspect_database(
            self._system_database_path,
            TCCDatabaseScope.SYSTEM,
            should_inspect=advanced,
        )
        generated_at = (self._now or datetime.now().astimezone()).isoformat(
            timespec="seconds"
        )
        warnings = _build_warnings(
            sip,
            boot_args,
            amfipass_detected,
            user_database,
            system_database,
        )
        commands = (
            _command_execution(
                "macOS build",
                ["/usr/bin/sw_vers", "-buildVersion"],
                build_result,
            ),
            _command_execution(
                "SIP",
                ["/usr/bin/csrutil", "status"],
                sip_result,
            ),
            _command_execution(
                "boot-args",
                ["/usr/sbin/nvram", "boot-args"],
                boot_result,
            ),
        )
        return DiagnosticReport(
            generated_at=generated_at,
            macos_version=platform.mac_ver()[0] or "unknown",
            macos_build=_first_nonempty_line(build_result.stdout),
            advanced=advanced,
            sip=sip,
            boot_args=boot_args,
            amfipass_detected=amfipass_detected,
            amfipass_locations=amfipass_locations,
            user_database=user_database,
            system_database=system_database,
            likely_missing_full_disk_access=(
                _likely_missing_full_disk_access(user_database)
            ),
            warnings=warnings,
            commands=commands,
            error_explanations=COMMON_ERROR_EXPLANATIONS,
        )

    def _inspect_database(
        self,
        path: Path,
        scope: TCCDatabaseScope,
        *,
        should_inspect: bool,
    ) -> DatabaseDiagnostic:
        exists = path.is_file()
        readable = os.access(path, os.R_OK) if exists else False
        writable = os.access(path, os.W_OK) if exists else False
        if not exists:
            return DatabaseDiagnostic(
                path=path,
                scope=scope,
                exists=False,
                posix_readable=False,
                posix_writable=False,
                schema_readable=False,
                access_row_count=None,
                schema_columns=(),
                error="数据库文件不存在。",
            )
        if not should_inspect:
            return DatabaseDiagnostic(
                path=path,
                scope=scope,
                exists=True,
                posix_readable=readable,
                posix_writable=writable,
                schema_readable=False,
                access_row_count=None,
                schema_columns=(),
                error="系统级 schema 检查未启用 advanced 模式。",
            )
        try:
            inspection = TCCDatabase(path, scope).inspect()
        except TCCAssistantError as exc:
            return DatabaseDiagnostic(
                path=path,
                scope=scope,
                exists=True,
                posix_readable=readable,
                posix_writable=writable,
                schema_readable=False,
                access_row_count=None,
                schema_columns=(),
                error=str(exc),
            )
        return DatabaseDiagnostic(
            path=path,
            scope=scope,
            exists=True,
            posix_readable=readable,
            posix_writable=writable,
            schema_readable=True,
            access_row_count=inspection.access_row_count,
            schema_columns=inspection.schema.columns,
        )


COMMON_ERROR_EXPLANATIONS = (
    "database is locked：先退出相关应用，避免与 tccd 或其他数据库工具同时写入。",
    (
        "unable to open database file / permission denied：检查完全磁盘访问权限、"
        "文件权限；系统级写入必须请求管理员授权。"
    ),
    "SIP 已启用：受保护系统路径和部分数据库写入可能被拒绝，本工具不会自动关闭 SIP。",
    (
        "TCC 请求链路不工作：浏览器功能可能由 Helper 进程触发，"
        "应确认实际发起请求的 Bundle ID，而不是默认注入所有 Helper。"
    ),
    "应用更新或重签：TCC 可能按代码身份匹配记录，签名变化后需要重新授权。",
)


def parse_sip_result(result: ProcessResult) -> SIPDiagnostic:
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    lines = tuple(line.strip() for line in output.splitlines() if line.strip())
    if result.returncode != 0 or result.error:
        return SIPDiagnostic(
            state=SIPState.ERROR,
            summary=result.error or "无法读取 SIP 状态。",
            details=lines,
        )
    first_line = lines[0].casefold() if lines else ""
    if "status: enabled" in first_line:
        state = SIPState.ENABLED
    elif "status: disabled" in first_line:
        state = SIPState.DISABLED
    elif "status: unknown" in first_line:
        state = SIPState.UNKNOWN
    else:
        state = SIPState.UNKNOWN
    return SIPDiagnostic(
        state=state,
        summary=lines[0] if lines else "csrutil 未返回状态。",
        details=lines[1:],
    )


def parse_boot_args_result(result: ProcessResult) -> BootArgsDiagnostic:
    if result.error:
        return BootArgsDiagnostic(
            state=BootArgsState.ERROR,
            raw_value="",
            arguments=(),
            detected_flags=(),
            error=result.error,
        )
    if result.returncode != 0:
        combined = f"{result.stdout}\n{result.stderr}".casefold()
        state = (
            BootArgsState.NOT_SET
            if "data was not found" in combined or "not found" in combined
            else BootArgsState.ERROR
        )
        return BootArgsDiagnostic(
            state=state,
            raw_value="",
            arguments=(),
            detected_flags=(),
            error=None if state is BootArgsState.NOT_SET else combined.strip(),
        )

    output = result.stdout.strip()
    value = output
    if "\t" in output:
        value = output.split("\t", 1)[1].strip()
    elif output.startswith("boot-args "):
        value = output[len("boot-args ") :].strip()
    if not value:
        return BootArgsDiagnostic(
            state=BootArgsState.NOT_SET,
            raw_value="",
            arguments=(),
            detected_flags=(),
        )
    try:
        arguments = tuple(shlex.split(value))
    except ValueError:
        arguments = tuple(value.split())
    markers = DiagnosticsCollector.BOOT_ARG_MARKERS
    flags = tuple(marker for marker in markers if marker in arguments)
    return BootArgsDiagnostic(
        state=BootArgsState.PRESENT,
        raw_value=value,
        arguments=arguments,
        detected_flags=flags,
    )


def render_markdown(report: DiagnosticReport) -> str:
    user_db = report.user_database
    system_db = report.system_database
    lines = [
        f"# {APP_NAME} · {PERMISSION_MODULE_NAME}诊断报告",
        "",
        f"- 生成时间：{report.generated_at}",
        f"- macOS：{report.macos_version}",
        f"- 构建版本：{report.macos_build or '未知'}",
        f"- 高级诊断：{'是' if report.advanced else '否'}",
        "",
        "## SIP",
        "",
        f"- 状态：`{report.sip.state.value}`",
        f"- 摘要：{report.sip.summary}",
    ]
    lines.extend(f"- {detail}" for detail in report.sip.details)

    lines.extend(
        [
            "",
            "## boot-args",
            "",
            f"- 状态：`{report.boot_args.state.value}`",
            f"- 原始参数：`{report.boot_args.raw_value or '无'}`",
            f"- 检测标志：{', '.join(report.boot_args.detected_flags) or '无'}",
            f"- AMFIPass：{'检测到' if report.amfipass_detected else '未检测到'}",
        ]
    )
    lines.extend(f"- AMFIPass 路径：{path}" for path in report.amfipass_locations)

    lines.extend(
        [
            "",
            "## TCC 数据库",
            "",
            "| 作用域 | 路径 | 存在 | POSIX 可读 | POSIX 可写 | schema 可读 | 记录数 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
            _database_row(user_db),
            _database_row(system_db),
            "",
            (
                f"- 可能缺少完全磁盘访问权限："
                f"{'是' if report.likely_missing_full_disk_access else '否'}"
            ),
        ]
    )
    for database in (user_db, system_db):
        if database.error:
            lines.append(f"- {database.scope.value} 错误：{database.error}")

    lines.extend(["", "## access 表结构", ""])
    schemas = [
        (database.scope.value, database.schema_columns)
        for database in (user_db, system_db)
        if database.schema_columns
    ]
    if not schemas:
        lines.append("未读取到 access 表结构。")
    for scope, columns in schemas:
        lines.extend(
            [
                f"### {scope}",
                "",
                "| cid | 字段 | 类型 | 非空 | 主键 |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for column in columns:
            lines.append(
                f"| {column.cid} | {_md(column.name)} | {_md(column.type_name)} | "
                f"{'是' if column.not_null else '否'} | "
                f"{'是' if column.primary_key else '否'} |"
            )
        lines.append("")

    lines.extend(["## 警告", ""])
    if report.warnings:
        lines.extend(f"- {warning}" for warning in report.warnings)
    else:
        lines.append("未发现额外的环境冲突警告。")

    lines.extend(["", "## 命令返回码", ""])
    for command in report.commands:
        lines.append(
            f"- {command.label}：`{command.returncode}` ({', '.join(command.command)})"
        )

    lines.extend(["", "## 常见错误解释", ""])
    lines.extend(f"- {item}" for item in report.error_explanations)
    lines.extend(
        [
            "",
            (
                "> 本报告不包含权限用途说明或其他个人文件内容。"
                "工具不会自动修改 OpenCore config.plist、SIP 或 AMFI 配置。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_diagnostic_report(
    report: DiagnosticReport,
    output_path: str | Path,
    *,
    report_format: str = "markdown",
) -> Path:
    """Write an atomic, user-private JSON or Markdown report."""

    path = Path(output_path).expanduser().absolute()
    normalized = report_format.casefold()
    if normalized in {"md", "markdown"}:
        content = report.to_markdown()
        normalized = "markdown"
    elif normalized == "json":
        content = json.dumps(
            report.to_dict(),
            ensure_ascii=False,
            indent=2,
        )
    else:
        raise ValueError(f"不支持的诊断报告格式：{report_format}")

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".TCC-report-",
        suffix=f".{normalized}",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file_handle:
            file_handle.write(content)
            file_handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _build_warnings(
    sip: SIPDiagnostic,
    boot_args: BootArgsDiagnostic,
    amfipass_detected: bool,
    user_database: DatabaseDiagnostic,
    system_database: DatabaseDiagnostic,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if sip.state is SIPState.ENABLED:
        warnings.append("SIP 已启用，TCC 数据库写入可能被系统拒绝。")
    elif sip.state is SIPState.UNKNOWN:
        warnings.append("SIP 处于未知或自定义配置，行为可能与标准 macOS 不同。")
    elif sip.state is SIPState.ERROR:
        warnings.append("无法可靠读取 SIP 状态。")

    flags = set(boot_args.detected_flags)
    if "amfi=0x80" in flags:
        warnings.append("检测到 amfi=0x80，AMFI 校验被放宽。")
    if "amfi_get_out_of_my_way=0x1" in flags:
        warnings.append("检测到 amfi_get_out_of_my_way=0x1。")
    if "ipc_control_port_options=0" in flags:
        warnings.append("检测到 ipc_control_port_options=0。")
    if amfipass_detected and "amfi=0x80" in flags:
        warnings.append(
            "同时检测到 AMFIPass 与 amfi=0x80，两者可能冲突；"
            "本工具不会自动修改 config.plist。"
        )

    if not user_database.exists:
        warnings.append("用户级 TCC 数据库不存在。")
    elif not user_database.schema_readable:
        warnings.append("用户级 TCC 数据库无法读取 access 表结构。")
    if user_database.exists and not user_database.posix_writable:
        warnings.append("用户级 TCC 数据库的 POSIX 权限当前不可写。")
    if not system_database.exists:
        warnings.append("系统级 TCC 数据库不存在。")
    return tuple(warnings)


def _likely_missing_full_disk_access(database: DatabaseDiagnostic) -> bool:
    if not database.exists or database.schema_readable:
        return False
    error = (database.error or "").casefold()
    markers = (
        "完全磁盘访问",
        "permission",
        "authorization",
        "unable to open",
        "无法只读打开",
    )
    return any(marker in error for marker in markers)


def _command_execution(
    label: str,
    command: Sequence[str],
    result: ProcessResult,
) -> CommandExecution:
    return CommandExecution(
        label=label,
        command=tuple(command),
        returncode=result.returncode,
        completed=result.error is None,
    )


def _first_nonempty_line(output: str) -> str | None:
    for line in output.splitlines():
        value = line.strip()
        if value:
            return value
    return None


def _database_row(database: DatabaseDiagnostic) -> str:
    return (
        f"| {database.scope.value} | {_md(str(database.path))} | "
        f"{'是' if database.exists else '否'} | "
        f"{'是' if database.posix_readable else '否'} | "
        f"{'是' if database.posix_writable else '否'} | "
        f"{'是' if database.schema_readable else '否'} | "
        f"{database.access_row_count if database.access_row_count is not None else '-'} |"
    )


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
