"""月星BAS工具箱命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from tcc_permission_assistant import __version__
from tcc_permission_assistant.branding import APP_NAME, PERMISSION_MODULE_NAME
from tcc_permission_assistant.core.backup import BackupManager
from tcc_permission_assistant.core.diagnostics import (
    DiagnosticsCollector,
    write_diagnostic_report,
)
from tcc_permission_assistant.core.errors import TCCAssistantError
from tcc_permission_assistant.core.injector import (
    CONFIRMATION_PHRASE,
    InjectionConfirmation,
    build_injection_plan,
    execute_injection,
)
from tcc_permission_assistant.core.logger import (
    AuditLogger,
    configure_logging,
    get_audit_logger,
)
from tcc_permission_assistant.core.models import (
    AppScanResult,
    DatabaseInspection,
    InjectionPlan,
    InjectionResult,
    PermissionAction,
    PermissionDeclaration,
    PermissionSource,
    PermissionStatus,
    SigningStatus,
    TCCDatabaseScope,
)
from tcc_permission_assistant.core.permission_map import (
    get_service_definition,
    resolve_service,
)
from tcc_permission_assistant.core.restore import (
    SYSTEM_RESTORE_PHRASE,
    USER_RESTORE_PHRASE,
    RestoreConfirmation,
    build_restore_plan,
    execute_restore,
)
from tcc_permission_assistant.core.scanner import AppScanner
from tcc_permission_assistant.core.tcc_db import TCCDatabase, tcc_database_path

_SIGNING_LABELS = {
    SigningStatus.SIGNED: "已签名",
    SigningStatus.ADHOC: "ad-hoc 签名",
    SigningStatus.UNSIGNED: "未签名",
    SigningStatus.INVALID: "签名信息异常",
    SigningStatus.UNKNOWN: "未知",
}

_SOURCE_LABELS = {
    PermissionSource.INFO_PLIST_USAGE: "Info.plist 用途说明",
    PermissionSource.ENTITLEMENT: "entitlements",
}

_PERMISSION_STATUS_LABELS = {
    PermissionStatus.NO_RECORD: "无记录",
    PermissionStatus.ALLOWED: "允许",
    PermissionStatus.DENIED: "拒绝",
    PermissionStatus.UNKNOWN: "未知",
}

_SCOPE_LABELS = {
    TCCDatabaseScope.USER: "用户级",
    TCCDatabaseScope.SYSTEM: "系统级",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yuexing-bas",
        description=f"{APP_NAME} · {PERMISSION_MODULE_NAME}",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出更详细的运行日志",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser(
        "scan",
        help="只读扫描一个 .app",
        description="读取 Info.plist、代码签名和 entitlements，不修改 TCC 数据库。",
    )
    scan_parser.add_argument("app", help="要扫描的 .app 路径")
    scan_parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读 JSON",
    )

    inspect_parser = subparsers.add_parser(
        "inspect-db",
        help="只读检查 TCC 数据库",
        description=("动态读取 access 表结构并查询白名单权限。本命令不会写入数据库。"),
    )
    inspect_parser.add_argument(
        "--scope",
        choices=[scope.value for scope in TCCDatabaseScope],
        default=TCCDatabaseScope.USER.value,
        help="数据库作用域，默认 user",
    )
    inspect_parser.add_argument(
        "--advanced",
        action="store_true",
        help="允许只读检查系统级数据库，必须与 --scope system 配合",
    )
    inspect_parser.add_argument(
        "--client",
        help="按 Bundle ID 查询权限状态",
    )
    inspect_parser.add_argument(
        "--service",
        action="append",
        help="限定 TCC service，可重复使用或使用短名称，如 Camera",
    )
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读 JSON",
    )

    generate_parser = subparsers.add_parser(
        "generate",
        help="生成 SQL，不执行",
        description="根据当前数据库状态生成 UPDATE 或 INSERT，不写入数据库。",
    )
    _add_injection_arguments(generate_parser)
    generate_parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读 JSON",
    )

    inject_parser = subparsers.add_parser(
        "inject",
        help="dry-run 或确认后注入用户级权限",
        description=(
            "默认 dry-run。只有使用 --execute 并完成交互确认后才会备份并写入。"
            "本阶段禁止写入系统级数据库。"
        ),
    )
    _add_injection_arguments(inject_parser)
    execution_group = inject_parser.add_mutually_exclusive_group()
    execution_group.add_argument(
        "--dry-run",
        action="store_true",
        help="只生成并显示 SQL，不写入（默认）",
    )
    execution_group.add_argument(
        "--execute",
        action="store_true",
        help="请求执行写入；随后仍需完成交互确认",
    )
    inject_parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读 JSON；执行确认提示写入 stderr",
    )

    restore_parser = subparsers.add_parser(
        "restore",
        help="列出或恢复受管理的 TCC 备份",
        description=(
            "默认 dry-run。恢复前自动备份当前数据库。"
            "系统级恢复需要 --advanced 和管理员授权。"
        ),
    )
    restore_source = restore_parser.add_mutually_exclusive_group(required=True)
    restore_source.add_argument(
        "--list",
        action="store_true",
        help="列出指定作用域的备份",
    )
    restore_source.add_argument(
        "--file",
        help="受管理备份目录中的 .bak 文件",
    )
    restore_parser.add_argument(
        "--scope",
        choices=[scope.value for scope in TCCDatabaseScope],
        default=TCCDatabaseScope.USER.value,
        help="恢复作用域，默认 user",
    )
    restore_parser.add_argument(
        "--advanced",
        action="store_true",
        help="允许系统级备份恢复，必须与 --scope system 配合",
    )
    restore_execution = restore_parser.add_mutually_exclusive_group()
    restore_execution.add_argument(
        "--dry-run",
        action="store_true",
        help="只显示恢复计划（默认）",
    )
    restore_execution.add_argument(
        "--execute",
        action="store_true",
        help="请求执行恢复；随后仍需完成交互确认",
    )
    restore_parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读 JSON",
    )

    diagnose_parser = subparsers.add_parser(
        "diagnose",
        help="生成 SIP、AMFI 与 TCC 数据库诊断报告",
        description="只读收集诊断信息，可导出 Markdown 或 JSON。",
    )
    diagnose_parser.add_argument(
        "--output",
        help="报告输出路径，如 report.md 或 report.json",
    )
    diagnose_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        help="输出格式；未指定时根据扩展名推断，默认 markdown",
    )
    diagnose_parser.add_argument(
        "--advanced",
        action="store_true",
        help="只读检查系统级 TCC.db 的 access schema",
    )
    return parser


def _add_injection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--bundle",
        required=True,
        help="目标应用的 Bundle ID",
    )
    parser.add_argument(
        "--service",
        required=True,
        help="白名单 TCC service，如 Camera 或 kTCCServiceCamera",
    )
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        "--allow",
        dest="action",
        action="store_const",
        const=PermissionAction.ALLOW.value,
        help="写入允许状态（auth_value=2）",
    )
    action_group.add_argument(
        "--deny",
        dest="action",
        action="store_const",
        const=PermissionAction.DENY.value,
        help="写入拒绝状态（auth_value=0）",
    )
    parser.add_argument(
        "--indirect-object",
        help="Apple Events 权限的目标应用或 Bundle ID",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    audit = configure_logging(verbose=args.verbose)

    try:
        if args.command == "scan":
            result = AppScanner(audit_logger=audit).scan(args.app)
            audit.event(
                "scan",
                path=result.path,
                bundle_id=result.bundle_id,
                signing_status=result.signing.status.value,
                services=[service.value for service in result.recommended_services],
                warning_count=len(result.warnings),
            )
            if args.json:
                _print_scan_json(result)
            else:
                _print_scan_text(result)
            return 0
        if args.command == "inspect-db":
            _inspect_database(args, audit)
            return 0
        if args.command == "generate":
            _generate_plan(args, audit)
            return 0
        if args.command == "inject":
            return _inject(args, audit)
        if args.command == "restore":
            return _restore(args, audit)
        if args.command == "diagnose":
            return _diagnose(args, audit)
    except TCCAssistantError as exc:
        get_audit_logger().event(
            "error",
            command=args.command,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        get_audit_logger().event(
            "cancelled",
            command=args.command,
        )
        print("已取消。", file=sys.stderr)
        return 130
    return 1


def _print_scan_json(result: AppScanResult) -> None:
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def _print_scan_text(result: AppScanResult) -> None:
    print(f"应用：{result.name}")
    print(f"路径：{result.path}")
    print(f"Bundle ID：{result.bundle_id}")
    if result.short_version or result.bundle_version:
        version_parts = []
        if result.short_version:
            version_parts.append(result.short_version)
        if result.bundle_version:
            version_parts.append(f"build {result.bundle_version}")
        print(f"版本：{' / '.join(version_parts)}")

    signing_label = _SIGNING_LABELS[result.signing.status]
    print(f"代码签名：{signing_label}")
    if result.signing.team_id:
        print(f"Team ID：{result.signing.team_id}")
    elif result.signing.signed:
        print("Team ID：未发现")
    for authority in result.signing.authorities:
        print(f"签名证书：{authority}")
    if result.signing.error:
        print(f"签名诊断：{result.signing.error}")

    print("权限声明：")
    if not result.permissions:
        print("  （无）")
    for declaration in result.permissions:
        _print_permission(declaration)

    print("建议检查的 TCC service：")
    if not result.recommended_services:
        print("  （无）")
    for service in result.recommended_services:
        definition = get_service_definition(service)
        print(f"  - {definition.display_name}：{service.value}")

    print("风险提示：")
    for warning in result.warnings:
        print(f"  - {warning}")


def _print_permission(declaration: PermissionDeclaration) -> None:
    definition = get_service_definition(declaration.service)
    print(f"  - {definition.display_name} ({declaration.service.value})")
    print(
        f"    来源：{_SOURCE_LABELS[declaration.source]} [{declaration.evidence_key}]"
    )
    if declaration.description:
        print(f"    用途说明：{declaration.description}")


def _inspect_database(
    args: argparse.Namespace,
    audit: AuditLogger,
) -> None:
    scope = TCCDatabaseScope(args.scope)
    if scope is TCCDatabaseScope.SYSTEM and not args.advanced:
        raise TCCAssistantError("检查系统级 TCC 数据库必须显式使用 --advanced。")

    selected_services = _selected_services(args.service)
    database = TCCDatabase(
        tcc_database_path(scope),
        scope=scope,
    )
    inspection = database.inspect()
    lookups = (
        database.lookup_permissions(args.client, selected_services)
        if args.client
        else ()
    )
    audit.event(
        "inspect_db",
        scope=scope.value,
        database_path=database.path,
        row_count=inspection.access_row_count,
        client=args.client,
        statuses={lookup.service.value: lookup.status.value for lookup in lookups},
    )

    if args.json:
        _print_inspection_json(
            inspection,
            selected_services=selected_services,
            client=args.client,
            lookups=lookups,
        )
        return
    _print_inspection_text(
        inspection,
        selected_services=selected_services,
        client=args.client,
        lookups=lookups,
    )


def _selected_services(values: list[str] | None):
    if not values:
        return None
    services = []
    for value in values:
        service = resolve_service(value)
        if service not in services:
            services.append(service)
    return tuple(services)


def _print_inspection_json(
    inspection: DatabaseInspection,
    *,
    selected_services,
    client: str | None,
    lookups,
) -> None:
    payload = inspection.to_dict()
    if selected_services is not None:
        selected = set(selected_services)
        payload["supported_service_counts"] = [
            item
            for item in payload["supported_service_counts"]
            if item["service"] in {service.value for service in selected}
        ]
    if client:
        payload["client"] = client
        payload["permissions"] = [lookup.to_dict() for lookup in lookups]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_inspection_text(
    inspection: DatabaseInspection,
    *,
    selected_services,
    client: str | None,
    lookups,
) -> None:
    print(f"数据库路径：{inspection.path}")
    print(f"作用域：{_SCOPE_LABELS[inspection.scope]}")
    print("访问模式：只读")
    if inspection.size_bytes is not None:
        print(f"文件大小：{inspection.size_bytes} 字节")
    print(f"access 总记录数：{inspection.access_row_count}")

    print("access 表结构：")
    for column in inspection.schema.columns:
        flags = []
        if column.primary_key:
            flags.append("主键")
        if column.not_null:
            flags.append("非空")
        suffix = f" [{'，'.join(flags)}]" if flags else ""
        print(f"  - {column.name} {column.type_name}{suffix}")

    selected = set(selected_services) if selected_services is not None else None
    print("白名单 service 记录数：")
    displayed_count = 0
    for item in inspection.supported_service_counts:
        if selected is not None and item.service not in selected:
            continue
        definition = get_service_definition(item.service)
        print(f"  - {definition.display_name}：{item.count}")
        displayed_count += 1
    if displayed_count == 0:
        print("  （无）")

    if not client:
        print("提示：使用 --client BUNDLE_ID 查询单个应用的权限状态。")
        return

    print(f"客户端：{client}")
    for lookup in lookups:
        definition = get_service_definition(lookup.service)
        status_label = _PERMISSION_STATUS_LABELS[lookup.status]
        print(f"  - {definition.display_name}：{status_label} ({lookup.service.value})")
        for record in lookup.records:
            print(
                f"    auth_value={record.auth_value!r}，"
                f"auth_reason={record.auth_reason!r}，"
                f"auth_version={record.auth_version!r}，"
                f"client_type={record.client_type!r}"
            )


def _generate_plan(args: argparse.Namespace, audit: AuditLogger) -> None:
    plan = _build_cli_injection_plan(args)
    audit.event(
        "generate_sql",
        database_path=plan.database_path,
        bundle_id=plan.bundle_id,
        service=plan.service.value,
        action=plan.action.value,
        operation=plan.operation.value,
        sql=plan.statement,
    )
    if args.json:
        print(
            json.dumps(
                {"dry_run": True, "plan": plan.to_dict()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    _print_injection_plan(plan)
    print("模式：仅生成，未写入数据库。")


def _inject(args: argparse.Namespace, audit: AuditLogger) -> int:
    plan = _build_cli_injection_plan(args)
    if not args.execute:
        audit.event(
            "inject_dry_run",
            database_path=plan.database_path,
            bundle_id=plan.bundle_id,
            service=plan.service.value,
            action=plan.action.value,
            operation=plan.operation.value,
            sql=plan.statement,
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "executed": False,
                        "plan": plan.to_dict(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            _print_injection_plan(plan)
            print("模式：dry-run，未备份、未写入数据库。")
        return 0

    preview_stream = sys.stderr if args.json else sys.stdout
    _print_injection_plan(plan, stream=preview_stream)
    confirmation = _prompt_injection_confirmation()
    result = execute_injection(plan, confirmation)
    audit.event(
        "inject",
        database_path=result.plan.database_path,
        bundle_id=result.plan.bundle_id,
        service=result.plan.service.value,
        action=result.plan.action.value,
        operation=result.plan.operation.value,
        sql=result.plan.statement,
        backup_path=result.backup.path,
        rows_changed=result.rows_changed,
        verification=result.verification.actual_status.value,
        success=result.success,
        rolled_back=result.rolled_back,
        rollback_error=result.rollback_error,
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_injection_result(result)
    return 0 if result.success else 2


def _build_cli_injection_plan(args: argparse.Namespace) -> InjectionPlan:
    database = TCCDatabase(
        tcc_database_path(TCCDatabaseScope.USER),
        scope=TCCDatabaseScope.USER,
    )
    return build_injection_plan(
        database,
        args.bundle,
        args.service,
        args.action,
        indirect_object_identifier=args.indirect_object,
    )


def _print_injection_plan(
    plan: InjectionPlan,
    *,
    stream=None,
) -> None:
    output = stream or sys.stdout
    definition = get_service_definition(plan.service)
    operation_label = (
        "更新现有记录" if plan.operation.value == "update" else "插入新记录"
    )
    action_label = "允许" if plan.action is PermissionAction.ALLOW else "拒绝"
    print("待执行变更：", file=output)
    print(f"  数据库：{plan.database_path}", file=output)
    print(f"  作用域：{_SCOPE_LABELS[plan.scope]}", file=output)
    print(f"  Bundle ID：{plan.bundle_id}", file=output)
    print(
        f"  权限：{definition.display_name} ({plan.service.value})",
        file=output,
    )
    print(f"  操作：{operation_label}", file=output)
    print(
        f"  当前状态：{_PERMISSION_STATUS_LABELS[plan.current_status]}",
        file=output,
    )
    print(f"  目标状态：{action_label} (auth_value={plan.auth_value})", file=output)
    if plan.indirect_object_identifier is not None:
        print(
            f"  间接对象：{plan.indirect_object_identifier}",
            file=output,
        )
    print(f"  SQL：{plan.statement}", file=output)
    print(
        f"  参数：{json.dumps(list(plan.parameters), ensure_ascii=False)}",
        file=output,
    )
    print(f"  可复制 SQL：{plan.literal_sql}", file=output)
    print(
        f"  手动重置命令（不会自动执行）：{plan.reset_command}",
        file=output,
    )
    print(
        "  风险：修改 TCC 数据库可能受 SIP、AMFI、schema 和应用签名状态影响。",
        file=output,
    )


def _prompt_injection_confirmation() -> InjectionConfirmation:
    print(file=sys.stderr)
    print("警告：即将修改用户级 TCC 数据库。", file=sys.stderr)
    closed_answer = _read_confirmation_line("相关应用是否已经完全退出？[y/N]: ")
    applications_closed = closed_answer.strip().casefold() in {"y", "yes"}
    if not applications_closed:
        raise TCCAssistantError("未确认应用退出，已取消且未写入数据库。")
    phrase = _read_confirmation_line(
        f"输入 {CONFIRMATION_PHRASE} 确认执行（其他输入将取消）: "
    )
    return InjectionConfirmation(
        applications_closed=True,
        phrase=phrase,
    )


def _read_confirmation_line(prompt: str) -> str:
    print(prompt, end="", file=sys.stderr, flush=True)
    return sys.stdin.readline()


def _print_injection_result(result: InjectionResult) -> None:
    print(f"备份文件：{result.backup.path}")
    print(f"备份 SHA-256：{result.backup.sha256}")
    print(f"写入行数：{result.rows_changed}")
    verification = result.verification
    print(
        "验证结果："
        + ("成功" if verification.success else "失败")
        + f"（预期 {_PERMISSION_STATUS_LABELS[verification.expected_status]}，"
        + f"实际 {_PERMISSION_STATUS_LABELS[verification.actual_status]}）"
    )
    if result.rolled_back:
        print("已自动回滚到操作前备份。")
    elif result.rollback_error:
        print(f"自动回滚失败：{result.rollback_error}")
    print("请完全退出相关应用后重新打开测试。")


def _restore(args: argparse.Namespace, audit: AuditLogger) -> int:
    scope = TCCDatabaseScope(args.scope)
    if scope is TCCDatabaseScope.SYSTEM and not args.advanced:
        raise TCCAssistantError("系统级备份恢复必须显式使用 --advanced。")
    manager = BackupManager()
    if args.list:
        if args.execute:
            raise TCCAssistantError("--list 不能与 --execute 同时使用。")
        entries = manager.list_backup_entries(scope)
        audit.event(
            "list_backups",
            scope=scope.value,
            count=len(entries),
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "scope": scope.value,
                        "backups": [entry.to_dict() for entry in entries],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif entries:
            for entry in entries:
                print(f"{entry.modified_at}  {entry.size_bytes:>10} 字节  {entry.path}")
        else:
            print(f"{_SCOPE_LABELS[scope]}没有可用备份。")
        return 0

    plan = build_restore_plan(
        args.file,
        scope,
        backup_manager=manager,
    )
    if not args.execute:
        audit.event(
            "restore_dry_run",
            scope=scope.value,
            backup_path=plan.backup_path,
            target_path=plan.target_path,
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "executed": False,
                        "plan": plan.to_dict(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            _print_restore_plan(plan)
            print("模式：dry-run，未备份、未恢复。")
        return 0

    preview_stream = sys.stderr if args.json else sys.stdout
    _print_restore_plan(plan, stream=preview_stream)
    confirmation = _prompt_restore_confirmation(scope)
    result = execute_restore(
        plan,
        confirmation,
        backup_manager=manager,
    )
    audit.event(
        "restore",
        scope=scope.value,
        backup_path=result.plan.backup_path,
        target_path=result.plan.target_path,
        pre_restore_backup=(
            result.pre_restore_backup.path
            if result.pre_restore_backup is not None
            else None
        ),
        access_row_count=result.access_row_count,
        schema_column_count=result.schema_column_count,
        verified=result.verified,
        command_returncode=result.external_returncode,
    )
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_restore_result(result)
    return 0 if result.verified else 2


def _print_restore_plan(plan, *, stream=None) -> None:
    output = stream or sys.stdout
    print("待执行恢复：", file=output)
    print(f"  备份文件：{plan.backup_path}", file=output)
    print(f"  目标数据库：{plan.target_path}", file=output)
    print(f"  作用域：{_SCOPE_LABELS[plan.scope]}", file=output)
    print(
        "  恢复前自动备份当前数据库："
        + ("是" if plan.current_database_exists else "当前文件不存在，无"),
        file=output,
    )
    if plan.scope is TCCDatabaseScope.SYSTEM:
        print("  提权方式：osascript 管理员授权（不保存密码）", file=output)
    print("  风险：会替换目标 TCC 数据，完成后必须重启相关应用。", file=output)


def _prompt_restore_confirmation(
    scope: TCCDatabaseScope,
) -> RestoreConfirmation:
    print(file=sys.stderr)
    print("警告：即将恢复 TCC 数据库。", file=sys.stderr)
    closed_answer = _read_confirmation_line("相关应用是否已经完全退出？[y/N]: ")
    applications_closed = closed_answer.strip().casefold() in {"y", "yes"}
    if not applications_closed:
        raise TCCAssistantError("未确认应用退出，已取消且未恢复数据库。")
    phrase = (
        SYSTEM_RESTORE_PHRASE
        if scope is TCCDatabaseScope.SYSTEM
        else USER_RESTORE_PHRASE
    )
    confirmation = _read_confirmation_line(
        f"输入 {phrase} 确认恢复（其他输入将取消）: "
    )
    return RestoreConfirmation(
        applications_closed=True,
        phrase=confirmation,
    )


def _print_restore_result(result) -> None:
    if result.pre_restore_backup is not None:
        print(f"恢复前备份：{result.pre_restore_backup.path}")
        print(f"备份 SHA-256：{result.pre_restore_backup.sha256}")
    else:
        print("恢复前目标数据库不存在，未创建恢复前备份。")
    print(
        f"恢复验证：{'成功' if result.verified else '失败'}"
        f"（access 记录数 {result.access_row_count}，"
        f"字段数 {result.schema_column_count}）"
    )
    print("请完全退出并重新打开相关应用；如权限仍异常，请重启系统。")


def _diagnose(args: argparse.Namespace, audit: AuditLogger) -> int:
    collector = DiagnosticsCollector()
    report = collector.collect(advanced=args.advanced)
    report_format = args.format
    if report_format is None:
        report_format = (
            "json"
            if args.output and str(args.output).casefold().endswith(".json")
            else "markdown"
        )
    audit.event(
        "diagnose",
        advanced=args.advanced,
        output=args.output,
        format=report_format,
        sip=report.sip.state.value,
        boot_args_state=report.boot_args.state.value,
        detected_flags=list(report.boot_args.detected_flags),
        user_db_readable=report.user_database.schema_readable,
        system_db_exists=report.system_database.exists,
        warning_count=len(report.warnings),
    )
    for command in report.commands:
        audit.event(
            "command",
            label=command.label,
            command=list(command.command),
            returncode=command.returncode,
            completed=command.completed,
        )
    if args.output:
        try:
            output_path = write_diagnostic_report(
                report,
                args.output,
                report_format=report_format,
            )
        except (OSError, ValueError) as exc:
            raise TCCAssistantError(f"无法写入诊断报告：{exc}") from exc
        print(f"诊断报告已写入：{output_path}")
        return 0

    if report_format == "json":
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.to_markdown())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
