"""Install and restore the Xie Qingyu Studio OpenCanopy theme."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from tcc_permission_assistant.core.backup import default_backup_root
from tcc_permission_assistant.core.errors import TCCAssistantError

PLUTIL = "/usr/bin/plutil"
THEME_VARIANT = r"XieQingyu\Studio"
OPEN_CANOPY_TARGET_VERSION = "1.0.9"
MANIFEST_NAME = "theme-manifest.json"
THEME_DIRECTORY_NAME = "XieQingyu/Studio"


class OpenCoreThemeError(TCCAssistantError):
    """An OpenCanopy theme operation failed or was rejected."""


@dataclass(frozen=True, slots=True)
class ThemeCommandResult:
    returncode: int
    stdout: str
    stderr: str


class ThemeCommandRunner(Protocol):
    def run(self, command: Sequence[str]) -> ThemeCommandResult:
        """Run one plutil command without a shell."""


class SubprocessThemeRunner:
    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, command: Sequence[str]) -> ThemeCommandResult:
        try:
            completed = subprocess.run(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise OpenCoreThemeError("OpenCore 配置校验超时。") from exc
        except OSError as exc:
            raise OpenCoreThemeError(f"无法运行命令：{command[0]}") from exc
        return ThemeCommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


@dataclass(frozen=True, slots=True)
class ThemeBackupInfo:
    path: Path
    created_at: str
    oc_directory: Path | None
    had_theme: bool
    had_driver: bool
    legacy: bool = False


@dataclass(frozen=True, slots=True)
class ThemeInstallResult:
    backup: ThemeBackupInfo
    config_path: Path
    theme_target: Path
    driver_target: Path


@dataclass(frozen=True, slots=True)
class ThemeRestoreResult:
    restored_backup: ThemeBackupInfo
    pre_restore_backup: ThemeBackupInfo
    oc_directory: Path


def default_theme_root() -> Path:
    """Return the bundled or source-tree OpenCanopy theme resources."""

    candidates: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root is not None:
        candidates.append(Path(bundle_root) / "oc_theme")
    candidates.append(Path(__file__).resolve().parents[2] / "oc_theme")
    for candidate in candidates:
        if (candidate / THEME_DIRECTORY_NAME).is_dir():
            return candidate
    return candidates[-1]


class OpenCoreThemeManager:
    """Apply or restore a backed-up theme below a mounted EFI/OC directory."""

    def __init__(
        self,
        theme_root: str | Path | None = None,
        backup_root: str | Path | None = None,
        runner: ThemeCommandRunner | None = None,
        retention: int = 30,
    ) -> None:
        self.theme_root = (
            Path(theme_root).expanduser().resolve()
            if theme_root is not None
            else default_theme_root()
        )
        self.backup_directory = (
            Path(backup_root or default_backup_root()).expanduser().resolve()
            / "OpenCore"
        )
        self.runner = runner or SubprocessThemeRunner()
        self.retention = max(1, retention)

    @property
    def theme_source(self) -> Path:
        return self.theme_root / THEME_DIRECTORY_NAME

    @property
    def label_source(self) -> Path:
        return self.theme_root / "Label"

    @property
    def driver_source(self) -> Path:
        return self.theme_root / "OpenCanopy.efi"

    def install(
        self,
        oc_directory: str | Path,
        *,
        compatibility_confirmed: bool = False,
    ) -> ThemeInstallResult:
        if not compatibility_confirmed:
            raise OpenCoreThemeError(
                "应用前必须确认当前 OpenCore 与内置 OpenCanopy 驱动兼容"
                f"（目标版本 {OPEN_CANOPY_TARGET_VERSION}）。"
            )
        oc_directory = self._validate_oc_directory(oc_directory)
        self._validate_theme_assets()
        backup = self._create_backup(oc_directory, "XieQingyuStudio")
        backup_info = self._backup_info(backup)
        theme_target = oc_directory / "Resources/Image" / THEME_DIRECTORY_NAME
        driver_target = oc_directory / "Drivers/OpenCanopy.efi"
        config_path = oc_directory / "config.plist"
        try:
            self._replace_tree(self.theme_source, theme_target)
            self._copy_tree_over(self.label_source, oc_directory / "Resources/Label")
            driver_target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_copy_file(self.driver_source, driver_target)
            self._rewrite_config(config_path)
            self._lint(config_path)
        except Exception as exc:
            self._restore_payload(backup, oc_directory)
            if isinstance(exc, OpenCoreThemeError):
                raise
            raise OpenCoreThemeError(f"应用主题失败，已自动回滚：{exc}") from exc
        self._prune_backups()
        return ThemeInstallResult(
            backup=backup_info,
            config_path=config_path,
            theme_target=theme_target,
            driver_target=driver_target,
        )

    def restore(
        self,
        backup_path: str | Path,
        oc_directory: str | Path | None = None,
    ) -> ThemeRestoreResult:
        backup = self._validate_backup(backup_path)
        backup_info = self._backup_info(backup)
        target = (
            self._validate_oc_directory(oc_directory)
            if oc_directory is not None
            else (
                self._validate_oc_directory(backup_info.oc_directory)
                if backup_info.oc_directory is not None
                else None
            )
        )
        if target is None:
            raise OpenCoreThemeError(
                "旧版主题备份未记录 OC 目录，请先选择当前 EFI/OC 文件夹。"
            )
        pre_restore = self._create_backup(
            target,
            "XieQingyuStudio-pre-restore",
        )
        try:
            self._restore_payload(backup, target)
            self._lint(target / "config.plist")
        except Exception as exc:
            self._restore_payload(pre_restore, target)
            if isinstance(exc, OpenCoreThemeError):
                raise
            raise OpenCoreThemeError(f"还原主题失败，已自动回滚：{exc}") from exc
        self._prune_backups()
        return ThemeRestoreResult(
            restored_backup=backup_info,
            pre_restore_backup=self._backup_info(pre_restore),
            oc_directory=target,
        )

    def list_backups(self) -> tuple[ThemeBackupInfo, ...]:
        if not self.backup_directory.is_dir():
            return ()
        backups = [
            self._backup_info(path)
            for path in self.backup_directory.iterdir()
            if path.is_dir() and (path / "config.plist").is_file()
        ]
        return tuple(
            sorted(
                backups,
                key=lambda item: (item.created_at, item.path.name),
                reverse=True,
            )
        )

    def _validate_theme_assets(self) -> None:
        if not self.theme_source.is_dir():
            raise OpenCoreThemeError(f"主题资源目录不完整：{self.theme_source}")
        if not self.label_source.is_dir():
            raise OpenCoreThemeError(f"主题标签目录不完整：{self.label_source}")
        if not self.driver_source.is_file():
            raise OpenCoreThemeError(
                "缺少 OpenCanopy.efi。请从 OpenCore 官方发行包获取匹配版本，"
                f"放到：{self.driver_source}"
            )

    @staticmethod
    def _validate_oc_directory(path: str | Path | None) -> Path:
        if path is None:
            raise OpenCoreThemeError("请先选择已挂载的 EFI/OC 文件夹。")
        resolved = Path(path).expanduser().resolve()
        if resolved.name != "OC":
            raise OpenCoreThemeError("请选择 EFI 分区中的 EFI/OC 文件夹。")
        if not (resolved / "config.plist").is_file():
            raise OpenCoreThemeError(
                f"找不到 OpenCore 配置：{resolved / 'config.plist'}"
            )
        if not (resolved / "Resources/Label").is_dir():
            raise OpenCoreThemeError(f"找不到 OpenCore 标签目录：{resolved}")
        return resolved

    def _create_backup(self, oc_directory: Path, prefix: str) -> Path:
        self.backup_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        timestamp = datetime.now().astimezone()
        stem = f"{prefix}-{timestamp.strftime('%Y%m%d-%H%M%S-%f')}"
        for index in range(1000):
            suffix = "" if index == 0 else f"-{index:03d}"
            backup = self.backup_directory / f"{stem}{suffix}"
            try:
                backup.mkdir()
            except FileExistsError:
                continue
            break
        else:
            raise OpenCoreThemeError("无法创建唯一的主题备份目录。")

        config_path = oc_directory / "config.plist"
        shutil.copy2(config_path, backup / "config.plist")
        shutil.copy2(
            config_path,
            oc_directory
            / f"config.plist.xieqingyu-{timestamp.strftime('%Y%m%d-%H%M%S-%f')}",
        )
        self._copy_tree_over(oc_directory / "Resources/Label", backup / "Label")
        theme_target = oc_directory / "Resources/Image" / THEME_DIRECTORY_NAME
        had_theme = theme_target.is_dir()
        if had_theme:
            shutil.copytree(theme_target, backup / "Image-XieQingyu-Studio")
        driver_target = oc_directory / "Drivers/OpenCanopy.efi"
        had_driver = driver_target.is_file()
        if had_driver:
            shutil.copy2(driver_target, backup / "OpenCanopy.efi")

        manifest = {
            "version": 1,
            "created_at": timestamp.isoformat(timespec="seconds"),
            "oc_directory": str(oc_directory),
            "had_theme": had_theme,
            "had_driver": had_driver,
        }
        (backup / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (backup / "RESTORE.txt").write_text(
            "可使用月星BAS工具箱的“还原所选主题备份”恢复此目录。\n",
            encoding="utf-8",
        )
        return backup

    def _restore_payload(self, backup: Path, oc_directory: Path) -> None:
        backup_config = backup / "config.plist"
        if not backup_config.is_file():
            raise OpenCoreThemeError("主题备份缺少 config.plist。")
        self._atomic_copy_file(backup_config, oc_directory / "config.plist")
        backup_label = backup / "Label"
        if backup_label.is_dir():
            self._copy_tree_over(backup_label, oc_directory / "Resources/Label")

        theme_target = oc_directory / "Resources/Image" / THEME_DIRECTORY_NAME
        backup_theme = backup / "Image-XieQingyu-Studio"
        if backup_theme.is_dir():
            self._replace_tree(backup_theme, theme_target)
        else:
            self._remove_tree(theme_target, oc_directory)

        driver_target = oc_directory / "Drivers/OpenCanopy.efi"
        backup_driver = backup / "OpenCanopy.efi"
        if backup_driver.is_file():
            driver_target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_copy_file(backup_driver, driver_target)
        else:
            driver_target.unlink(missing_ok=True)

    def _rewrite_config(self, config_path: Path) -> None:
        try:
            with config_path.open("rb") as file_handle:
                config = plistlib.load(file_handle)
        except (OSError, plistlib.InvalidFileException, ValueError) as exc:
            raise OpenCoreThemeError("OpenCore config.plist 无法读取。") from exc
        if not isinstance(config, dict):
            raise OpenCoreThemeError("OpenCore config.plist 根节点格式无效。")
        boot = config.setdefault("Misc", {}).setdefault("Boot", {})
        boot["PickerMode"] = "External"
        boot["PickerVariant"] = THEME_VARIANT
        boot["PickerAttributes"] = 21
        drivers = config.setdefault("UEFI", {}).setdefault("Drivers", [])
        open_canopy = next(
            (
                driver
                for driver in drivers
                if isinstance(driver, dict) and driver.get("Path") == "OpenCanopy.efi"
            ),
            None,
        )
        if open_canopy is None:
            drivers.append(
                {
                    "Arguments": "",
                    "Comment": "Xie Qingyu Studio OpenCanopy theme",
                    "Enabled": True,
                    "HideVerbose": False,
                    "LoadEarly": False,
                    "Path": "OpenCanopy.efi",
                }
            )
        else:
            open_canopy["Enabled"] = True
        self._atomic_write_bytes(
            config_path,
            plistlib.dumps(config, sort_keys=False),
        )

    def _lint(self, config_path: Path) -> None:
        result = self.runner.run([PLUTIL, "-lint", str(config_path)])
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise OpenCoreThemeError(detail or "OpenCore config.plist 校验失败。")

    def _validate_backup(self, backup_path: str | Path) -> Path:
        candidate = Path(backup_path).expanduser().resolve()
        self.backup_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if candidate.parent != self.backup_directory.resolve():
            raise OpenCoreThemeError("只能还原本工具管理的 OpenCore 主题备份。")
        if not candidate.is_dir() or not (candidate / "config.plist").is_file():
            raise OpenCoreThemeError("主题备份不存在或内容不完整。")
        return candidate

    def _backup_info(self, backup: Path) -> ThemeBackupInfo:
        manifest_path = backup / MANIFEST_NAME
        manifest: dict[str, object] = {}
        if manifest_path.is_file():
            try:
                value = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                value = {}
            if isinstance(value, dict):
                manifest = value
        created_at = str(
            manifest.get("created_at")
            or datetime.fromtimestamp(backup.stat().st_mtime)
            .astimezone()
            .isoformat(timespec="seconds")
        )
        oc_value = manifest.get("oc_directory")
        return ThemeBackupInfo(
            path=backup,
            created_at=created_at,
            oc_directory=Path(str(oc_value)) if oc_value else None,
            had_theme=bool(
                manifest.get("had_theme")
                if "had_theme" in manifest
                else (backup / "Image-XieQingyu-Studio").is_dir()
            ),
            had_driver=bool(
                manifest.get("had_driver")
                if "had_driver" in manifest
                else (backup / "OpenCanopy.efi").is_file()
            ),
            legacy=not manifest,
        )

    def _prune_backups(self) -> None:
        if not self.backup_directory.is_dir():
            return
        backups = sorted(
            (
                path
                for path in self.backup_directory.iterdir()
                if path.is_dir() and (path / "config.plist").is_file()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in backups[self.retention :]:
            try:
                shutil.rmtree(path)
            except OSError:
                continue

    @staticmethod
    def _copy_tree_over(source: Path, target: Path) -> None:
        target.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            destination = target / item.name
            if item.is_dir():
                shutil.copytree(item, destination, dirs_exist_ok=True)
            elif item.is_file():
                shutil.copy2(item, destination)

    @staticmethod
    def _replace_tree(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)

    @staticmethod
    def _remove_tree(target: Path, oc_directory: Path) -> None:
        resolved_target = target.resolve()
        if oc_directory not in resolved_target.parents:
            raise OpenCoreThemeError("拒绝删除 EFI/OC 目录之外的路径。")
        if resolved_target.exists():
            shutil.rmtree(resolved_target)

    def _atomic_copy_file(self, source: Path, target: Path) -> None:
        try:
            self._atomic_write_bytes(target, source.read_bytes())
        except OSError as exc:
            raise OpenCoreThemeError(f"无法原子写入 {target}：{exc}") from exc

    @staticmethod
    def _atomic_write_bytes(target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = 0o644
        if target.exists():
            try:
                mode = target.stat().st_mode & 0o777
            except OSError:
                pass
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as file_handle:
                file_handle.write(data)
                file_handle.flush()
                os.fsync(file_handle.fileno())
            try:
                os.chmod(temporary, mode)
            except OSError:
                pass
            os.replace(temporary, target)
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
