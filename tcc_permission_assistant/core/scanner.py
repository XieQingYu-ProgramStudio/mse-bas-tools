"""Read-only macOS application bundle scanner."""

from __future__ import annotations

import plistlib
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tcc_permission_assistant.core.errors import InvalidAppBundle, ScanError
from tcc_permission_assistant.core.localization import lproj_candidates
from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.core.models import (
    AppScanResult,
    PermissionDeclaration,
    PermissionSource,
    SigningInfo,
    SigningStatus,
    TCCService,
)
from tcc_permission_assistant.core.permission_map import (
    ENTITLEMENT_TO_SERVICE,
    USAGE_DESCRIPTION_TO_SERVICE,
)
from tcc_permission_assistant.core.security import validate_bundle_id
from tcc_permission_assistant.core.settings import LANGUAGE_SYSTEM


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured result of a non-shell subprocess."""

    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Injectable subprocess boundary used by scanner tests."""

    def run(self, command: Sequence[str]) -> CommandResult:
        """Run a command without a shell and capture text output."""


class SubprocessRunner:
    """Run commands with an argument list and no shell interpolation."""

    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, command: Sequence[str]) -> CommandResult:
        try:
            completed = subprocess.run(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise ScanError(f"找不到命令：{command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ScanError(f"命令执行超时：{command[0]}") from exc
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


def parse_signing_output(returncode: int, output: str) -> SigningInfo:
    """Parse ``codesign -dv --verbose=4`` diagnostics."""

    values: dict[str, list[str]] = {}
    for raw_line in output.splitlines():
        key, separator, value = raw_line.strip().partition("=")
        if not separator:
            continue
        values.setdefault(key, []).append(value.strip())

    identifier = _first_value(values, "Identifier")
    team_id = _first_value(values, "TeamIdentifier")
    if team_id and team_id.casefold() in {"not set", "none", "unknown"}:
        team_id = None
    authorities = tuple(
        authority
        for authority in values.get("Authority", ())
        if authority.casefold() not in {"(unavailable)", "unavailable"}
    )
    lowered = output.casefold()
    adhoc = (
        "signature=adhoc" in lowered
        or "(adhoc)" in lowered
        or "flags=0x2(adhoc)" in lowered
    )

    if returncode != 0:
        unsigned_markers = (
            "not signed at all",
            "code object is not signed",
            "is not signed",
        )
        if any(marker in lowered for marker in unsigned_markers):
            status = SigningStatus.UNSIGNED
        else:
            status = SigningStatus.INVALID
    elif adhoc:
        status = SigningStatus.ADHOC
    else:
        status = SigningStatus.SIGNED

    error = None
    if status in {SigningStatus.UNSIGNED, SigningStatus.INVALID}:
        error = _meaningful_line(output) or "codesign 未返回可用签名信息。"

    return SigningInfo(
        status=status,
        signed=status in {SigningStatus.SIGNED, SigningStatus.ADHOC},
        adhoc=status is SigningStatus.ADHOC,
        identifier=identifier,
        team_id=team_id,
        authorities=authorities,
        error=error,
    )


class AppScanner:
    """Inspect an app bundle without modifying it or reading TCC databases."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        codesign_path: str = "/usr/bin/codesign",
        audit_logger: AuditLogger | None = None,
        display_language: str = LANGUAGE_SYSTEM,
    ) -> None:
        self._runner = runner or SubprocessRunner()
        self._codesign_path = codesign_path
        self._audit_logger = audit_logger
        self.display_language = display_language

    def scan(self, app_path: str | Path) -> AppScanResult:
        path = self._validate_app_path(app_path)
        info_plist_path = path / "Contents" / "Info.plist"
        info = self._read_info_plist(info_plist_path)
        bundle_id = validate_bundle_id(info.get("CFBundleIdentifier"))

        signing = self._read_signing(path)
        localized = self._read_localized_strings(path)
        warnings: list[str] = []
        permissions = self._read_usage_descriptions(info, localized)
        permissions.extend(self._read_entitlements(path, signing, warnings))

        recommended: list[TCCService] = []
        for declaration in permissions:
            if declaration.service not in recommended:
                recommended.append(declaration.service)

        warnings.extend(self._risk_warnings(path, bundle_id, signing, permissions))
        return AppScanResult(
            name=self._application_name(info, path, localized),
            path=path,
            bundle_id=bundle_id,
            short_version=_optional_string(info.get("CFBundleShortVersionString")),
            bundle_version=_optional_string(info.get("CFBundleVersion")),
            signing=signing,
            permissions=tuple(permissions),
            recommended_services=tuple(recommended),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _validate_app_path(app_path: str | Path) -> Path:
        path = Path(app_path).expanduser()
        if path.suffix.casefold() != ".app":
            raise InvalidAppBundle(f"请选择 .app 应用包：{path}")
        if not path.is_dir():
            raise InvalidAppBundle(f"应用包不存在或不是目录：{path}")
        return path.absolute()

    @staticmethod
    def _read_info_plist(path: Path) -> dict[str, object]:
        if not path.is_file():
            raise InvalidAppBundle(f"缺少 Info.plist：{path}")
        try:
            with path.open("rb") as file_handle:
                payload = plistlib.load(file_handle)
        except (OSError, plistlib.InvalidFileException) as exc:
            raise ScanError(f"无法读取 Info.plist：{path}") from exc
        if not isinstance(payload, dict):
            raise ScanError("Info.plist 根节点必须是字典。")
        return payload

    def _read_signing(self, path: Path) -> SigningInfo:
        result = self._runner.run(
            [
                self._codesign_path,
                "-dv",
                "--verbose=4",
                str(path),
            ]
        )
        self._log_command("codesign signing", path, result.returncode)
        combined_output = "\n".join(
            part for part in (result.stdout, result.stderr) if part
        )
        return parse_signing_output(result.returncode, combined_output)

    @staticmethod
    def _read_usage_descriptions(
        info: Mapping[str, object],
        localized: Mapping[str, object],
    ) -> list[PermissionDeclaration]:
        declarations: list[PermissionDeclaration] = []
        for key, service in USAGE_DESCRIPTION_TO_SERVICE.items():
            if key not in info:
                continue
            description = _optional_string(localized.get(key) or info.get(key))
            declarations.append(
                PermissionDeclaration(
                    service=service,
                    source=PermissionSource.INFO_PLIST_USAGE,
                    evidence_key=key,
                    description=description,
                )
            )
        return declarations

    def _read_entitlements(
        self,
        path: Path,
        signing: SigningInfo,
        warnings: list[str],
    ) -> list[PermissionDeclaration]:
        if not signing.signed:
            return []
        result = self._runner.run(
            [
                self._codesign_path,
                "-d",
                "--entitlements",
                ":-",
                str(path),
            ]
        )
        self._log_command("codesign entitlements", path, result.returncode)
        if result.returncode != 0:
            warnings.append("无法读取应用 entitlements，建议检查代码签名状态。")
            return []

        entitlements = _parse_entitlements_plist(result.stdout)
        if entitlements is None:
            if result.stdout.strip():
                warnings.append("entitlements 输出无法解析，已跳过权限映射。")
            return []

        declarations: list[PermissionDeclaration] = []
        for key, service in ENTITLEMENT_TO_SERVICE.items():
            if entitlements.get(key) is True:
                declarations.append(
                    PermissionDeclaration(
                        service=service,
                        source=PermissionSource.ENTITLEMENT,
                        evidence_key=key,
                    )
                )
        return declarations

    def _log_command(self, label: str, path: Path, returncode: int) -> None:
        if self._audit_logger is None:
            return
        self._audit_logger.event(
            "command",
            label=label,
            command=[
                self._codesign_path,
                label,
                str(path),
            ],
            returncode=returncode,
        )

    def _application_name(
        self,
        info: Mapping[str, object],
        path: Path,
        localized: Mapping[str, object],
    ) -> str:
        for key in ("CFBundleDisplayName", "CFBundleName"):
            value = _optional_string(localized.get(key) or info.get(key))
            if value:
                return value
        return path.stem

    def _read_localized_strings(self, path: Path) -> dict[str, object]:
        resources = path / "Contents" / "Resources"
        for directory_name in lproj_candidates(self.display_language):
            strings_path = resources / f"{directory_name}.lproj" / "InfoPlist.strings"
            if not strings_path.is_file():
                continue
            result = self._runner.run(
                [
                    "/usr/bin/plutil",
                    "-convert",
                    "xml1",
                    "-o",
                    "-",
                    str(strings_path),
                ]
            )
            if result.returncode != 0:
                continue
            try:
                parsed = plistlib.loads(result.stdout.encode("utf-8"))
            except (plistlib.InvalidFileException, ValueError):
                continue
            if isinstance(parsed, dict):
                return parsed
        return {}

    @staticmethod
    def _risk_warnings(
        path: Path,
        bundle_id: str,
        signing: SigningInfo,
        permissions: Sequence[PermissionDeclaration],
    ) -> list[str]:
        warnings = [
            "Info.plist 中的用途说明只代表应用声明，不代表应用已获得 TCC 授权。",
            "更新、重新签名或替换应用可能改变 TCC 身份，已有授权可能失效。",
        ]
        if not permissions:
            warnings.append("未发现本工具支持映射的隐私权限声明。")

        helper_markers = (
            "/contents/frameworks/" in path.as_posix().casefold(),
            ".helper" in bundle_id.casefold(),
        )
        if any(helper_markers):
            warnings.append(
                "检测到应用可能包含 Helper 或自身是 Helper；"
                "浏览器 Helper 不应默认注入，请先确认实际调用权限的进程。"
            )

        if signing.status is SigningStatus.UNSIGNED:
            warnings.append("应用未签名，TCC 身份可能不稳定。")
        elif signing.status is SigningStatus.ADHOC:
            warnings.append("应用使用 ad-hoc 签名，更新或重签后可能需要重新授权。")
        elif signing.status is SigningStatus.INVALID:
            warnings.append("代码签名信息无法验证，请先检查应用完整性。")
        elif signing.team_id is None:
            warnings.append("未发现 Team ID，TCC 可能无法稳定识别应用身份。")
        return warnings


def _parse_entitlements_plist(output: str) -> dict[str, object] | None:
    payload = output.lstrip()
    if not payload:
        return None
    starts = [
        index
        for marker in ("<?xml", "<plist", "<!DOCTYPE plist")
        if (index := payload.find(marker)) >= 0
    ]
    if starts:
        payload = payload[min(starts) :]
    try:
        parsed = plistlib.loads(payload.encode("utf-8"))
    except (plistlib.InvalidFileException, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _first_value(values: Mapping[str, list[str]], key: str) -> str | None:
    items = values.get(key)
    return items[0] if items else None


def _optional_string(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _meaningful_line(output: str) -> str | None:
    for line in output.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None
