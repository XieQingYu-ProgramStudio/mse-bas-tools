"""Clear macOS System Settings attention badges without blocking updates."""

from __future__ import annotations

import hashlib
import os
import plistlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from tcc_permission_assistant.core.backup import default_backup_root
from tcc_permission_assistant.core.errors import TCCAssistantError

ATTENTION_KEY = "AttentionPrefBundleIDs"
DEFAULT_PREFERENCE_PATH = (
    Path.home() / "Library" / "Preferences" / "com.apple.systempreferences.plist"
)


class UpdateBadgeError(TCCAssistantError):
    """A System Settings badge preference operation failed."""


@dataclass(frozen=True, slots=True)
class PreferenceCommandResult:
    returncode: int
    stdout: str
    stderr: str


class PreferenceCommandRunner(Protocol):
    def run(self, command: Sequence[str]) -> PreferenceCommandResult:
        """Run one defaults or process command without a shell."""


class SubprocessPreferenceRunner:
    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, command: Sequence[str]) -> PreferenceCommandResult:
        import subprocess

        try:
            completed = subprocess.run(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateBadgeError(f"命令执行失败：{command[0]}") from exc
        return PreferenceCommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


@dataclass(frozen=True, slots=True)
class AttentionBadge:
    bundle_id: str
    value: object
    category: str
    is_update_related: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "value": self.value,
            "category": self.category,
            "is_update_related": self.is_update_related,
        }


@dataclass(frozen=True, slots=True)
class BadgeSnapshot:
    preference_path: Path
    items: tuple[AttentionBadge, ...]
    raw_preferences: dict[str, object]

    @property
    def update_items(self) -> tuple[AttentionBadge, ...]:
        return tuple(item for item in self.items if item.is_update_related)


@dataclass(frozen=True, slots=True)
class PreferenceBackup:
    path: Path
    source_path: Path
    created_at: str
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "source_path": str(self.source_path),
            "created_at": self.created_at,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class BadgeClearResult:
    cleared_keys: tuple[str, ...]
    remaining_items: tuple[AttentionBadge, ...]
    backup: PreferenceBackup

    def to_dict(self) -> dict[str, object]:
        return {
            "cleared_keys": list(self.cleared_keys),
            "remaining_items": [item.to_dict() for item in self.remaining_items],
            "backup": self.backup.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class BadgeRestoreResult:
    restored_from: Path
    pre_restore_backup: PreferenceBackup
    items: tuple[AttentionBadge, ...]


class UpdateBadgeManager:
    """Read, clear, backup, and restore System Settings attention items."""

    def __init__(
        self,
        preference_path: str | Path = DEFAULT_PREFERENCE_PATH,
        *,
        backup_root: str | Path | None = None,
        runner: PreferenceCommandRunner | None = None,
        retention: int = 50,
    ) -> None:
        self.preference_path = Path(preference_path).expanduser().absolute()
        self.backup_directory = (
            Path(backup_root or default_backup_root()) / "systempreferences"
        )
        self.runner = runner or SubprocessPreferenceRunner()
        self.retention = max(1, retention)

    def read(self) -> BadgeSnapshot:
        preferences = self._read_preferences()
        attention = preferences.get(ATTENTION_KEY)
        items: list[AttentionBadge] = []
        if isinstance(attention, dict):
            for key, value in attention.items():
                bundle_id = str(key)
                category, related = _classify_badge(bundle_id)
                items.append(
                    AttentionBadge(
                        bundle_id=bundle_id,
                        value=value,
                        category=category,
                        is_update_related=related,
                    )
                )
        items.sort(
            key=lambda item: (
                not item.is_update_related,
                item.bundle_id.casefold(),
            )
        )
        return BadgeSnapshot(
            preference_path=self.preference_path,
            items=tuple(items),
            raw_preferences=preferences,
        )

    def clear_badges(
        self,
        bundle_ids: Sequence[str],
        *,
        restart_ui: bool = True,
    ) -> BadgeClearResult:
        snapshot = self.read()
        selected = set(bundle_ids)
        current_keys = {item.bundle_id for item in snapshot.items}
        keys = tuple(sorted(selected & current_keys))
        if not keys:
            raise UpdateBadgeError("没有可清理的更新红点项目。")

        backup = self._backup_preferences(snapshot.raw_preferences)
        attention = dict(snapshot.raw_preferences.get(ATTENTION_KEY) or {})
        for key in keys:
            attention.pop(key, None)
        self._write_attention(attention)
        after = self.read()
        if set(keys) & {item.bundle_id for item in after.items}:
            raise UpdateBadgeError("红点偏好写入后验证失败。")
        if restart_ui:
            self._restart_settings_ui()
        return BadgeClearResult(
            cleared_keys=keys,
            remaining_items=after.items,
            backup=backup,
        )

    def list_backups(self) -> tuple[Path, ...]:
        if not self.backup_directory.is_dir():
            return ()
        return tuple(
            sorted(
                self.backup_directory.glob("com.apple.systempreferences-*.plist"),
                reverse=True,
            )
        )

    def restore(
        self,
        backup_path: str | Path,
        *,
        restart_ui: bool = True,
    ) -> BadgeRestoreResult:
        path = Path(backup_path).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise UpdateBadgeError("红点备份文件不存在。") from exc
        directory = self.backup_directory.expanduser().absolute()
        if resolved.parent != directory:
            raise UpdateBadgeError("只能恢复本工具管理的红点备份。")
        try:
            restored_preferences = plistlib.loads(resolved.read_bytes())
        except (OSError, plistlib.InvalidFileException) as exc:
            raise UpdateBadgeError("红点备份文件无效。") from exc
        if not isinstance(restored_preferences, dict):
            raise UpdateBadgeError("红点备份内容格式不正确。")

        current = self.read()
        pre_restore = self._backup_preferences(current.raw_preferences)
        restored_attention = restored_preferences.get(ATTENTION_KEY)
        if restored_attention is None:
            attention: dict[str, object] = {}
        elif isinstance(restored_attention, dict):
            attention = dict(restored_attention)
        else:
            raise UpdateBadgeError("红点备份中的 AttentionPrefBundleIDs 格式无效。")
        self._write_attention(attention)
        after = self.read()
        if restart_ui:
            self._restart_settings_ui()
        return BadgeRestoreResult(
            restored_from=resolved,
            pre_restore_backup=pre_restore,
            items=after.items,
        )

    def _read_preferences(self) -> dict[str, object]:
        result = self.runner.run(
            [
                "/usr/bin/defaults",
                "export",
                _defaults_domain(self.preference_path),
                "-",
            ]
        )
        if result.returncode != 0:
            if not self.preference_path.is_file():
                return {}
            raise UpdateBadgeError("无法读取 System Settings 偏好。")
        try:
            preferences = plistlib.loads(result.stdout.encode("utf-8"))
        except (plistlib.InvalidFileException, ValueError) as exc:
            raise UpdateBadgeError("System Settings 偏好内容无效。") from exc
        if not isinstance(preferences, dict):
            raise UpdateBadgeError("System Settings 偏好根节点格式不正确。")
        return preferences

    def _write_attention(self, attention: dict[str, object]) -> None:
        domain = _defaults_domain(self.preference_path)
        if not attention:
            command = [
                "/usr/bin/defaults",
                "delete",
                domain,
                ATTENTION_KEY,
            ]
        else:
            command = [
                "/usr/bin/defaults",
                "write",
                domain,
                ATTENTION_KEY,
                "-dict",
            ]
            for key, value in attention.items():
                command.append(str(key))
                command.extend(_defaults_value_arguments(value))
        result = self.runner.run(command)
        if result.returncode != 0:
            raise UpdateBadgeError(
                f"写入 System Settings 偏好失败：{result.stderr.strip()}"
            )

    def _backup_preferences(
        self,
        preferences: dict[str, object],
    ) -> PreferenceBackup:
        self.backup_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.backup_directory, 0o700)
        except OSError:
            pass
        timestamp = datetime.now().astimezone()
        prefix = f"com.apple.systempreferences-{timestamp.strftime('%Y%m%d-%H%M%S-%f')}"
        for index in range(1000):
            suffix = "" if index == 0 else f"-{index:03d}"
            path = self.backup_directory / f"{prefix}{suffix}.plist"
            if path.exists():
                continue
            data = plistlib.dumps(preferences, sort_keys=False)
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as file_handle:
                file_handle.write(data)
            self._prune_backups()
            return PreferenceBackup(
                path=path,
                source_path=self.preference_path,
                created_at=timestamp.isoformat(timespec="seconds"),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        raise UpdateBadgeError("无法创建唯一的红点偏好备份。")

    def _prune_backups(self) -> None:
        for path in self.list_backups()[self.retention :]:
            try:
                path.unlink()
            except OSError:
                continue

    def _restart_settings_ui(self) -> None:
        self.runner.run(["/usr/bin/killall", "System Settings"])
        self.runner.run(["/usr/bin/killall", "Dock"])


def _defaults_domain(preference_path: Path) -> str:
    if preference_path.suffix == ".plist":
        return str(preference_path.with_suffix(""))
    return str(preference_path)


def _classify_badge(bundle_id: str) -> tuple[str, bool]:
    normalized = bundle_id.casefold()
    if "software" in normalized and "update" in normalized:
        return "系统更新", True
    if "followupsettings" in normalized:
        return "设置后续提示", True
    return "其他设置提示", False


def _defaults_value_arguments(value: object) -> list[str]:
    if isinstance(value, bool):
        return ["-bool", "true" if value else "false"]
    if isinstance(value, int):
        return ["-int", str(value)]
    if isinstance(value, float):
        return ["-float", str(value)]
    if isinstance(value, str):
        return ["-string", value]
    raise UpdateBadgeError(f"无法保留复杂红点值类型：{type(value).__name__}")
