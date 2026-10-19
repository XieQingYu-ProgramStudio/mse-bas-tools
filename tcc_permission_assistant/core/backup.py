"""Consistent SQLite backups for TCC databases."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from tcc_permission_assistant.core.errors import BackupError
from tcc_permission_assistant.core.models import (
    BackupEntry,
    BackupInfo,
    TCCDatabaseScope,
)


def default_backup_root(home: Path | None = None) -> Path:
    """Return the application-owned backup directory."""

    return (
        (home or Path.home())
        / "Library"
        / "Application Support"
        / "TCCPermissionAssistant"
        / "Backups"
    )


class BackupManager:
    """Create timestamped backups without overwriting existing files."""

    def __init__(self, backup_root: str | Path | None = None) -> None:
        self.backup_root = Path(backup_root or default_backup_root()).expanduser()

    def directory_for_scope(self, scope: TCCDatabaseScope) -> Path:
        return self.backup_root / scope.value

    def create_backup(
        self,
        database_path: str | Path,
        scope: TCCDatabaseScope | str = TCCDatabaseScope.USER,
        now: datetime | None = None,
    ) -> BackupInfo:
        """Create, verify, and hash a consistent SQLite snapshot."""

        parsed_scope = TCCDatabaseScope(scope)
        source_path = Path(database_path).expanduser().absolute()
        if not source_path.is_file():
            raise BackupError(f"无法备份，数据库不存在：{source_path}")

        backup_directory = self.directory_for_scope(parsed_scope)
        try:
            backup_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(backup_directory, 0o700)
        except OSError as exc:
            raise BackupError(f"无法创建备份目录：{backup_directory}") from exc

        timestamp = now or datetime.now().astimezone()
        prefix = f"TCC-{parsed_scope.value}-{timestamp.strftime('%Y%m%d-%H%M%S-%f')}"

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".TCC-backup-",
            suffix=".tmp",
            dir=backup_directory,
        )
        os.close(file_descriptor)
        temporary_path = Path(temporary_name)
        final_path: Path | None = None
        try:
            os.chmod(temporary_path, 0o600)
            self._copy_database(source_path, temporary_path)
            final_path = self._reserve_backup_name(
                backup_directory,
                prefix,
                temporary_path,
            )
            os.chmod(final_path, 0o600)
        except BackupError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise BackupError(f"备份 TCC 数据库失败：{exc}") from exc
        finally:
            temporary_path.unlink(missing_ok=True)

        if final_path is None:
            raise BackupError("备份文件未能写入目标目录。")
        try:
            return BackupInfo(
                path=final_path,
                source_path=source_path,
                scope=parsed_scope,
                created_at=timestamp.isoformat(timespec="seconds"),
                size_bytes=final_path.stat().st_size,
                sha256=_sha256_file(final_path),
            )
        except OSError as exc:
            raise BackupError(f"无法校验备份文件：{final_path}") from exc

    def list_backups(
        self,
        scope: TCCDatabaseScope | str = TCCDatabaseScope.USER,
    ) -> tuple[Path, ...]:
        """List backup files for a scope, newest filename first."""

        parsed_scope = TCCDatabaseScope(scope)
        directory = self.directory_for_scope(parsed_scope)
        if not directory.is_dir():
            return ()
        return tuple(sorted(directory.glob("TCC-*.bak"), reverse=True))

    def list_backup_entries(
        self,
        scope: TCCDatabaseScope | str = TCCDatabaseScope.USER,
    ) -> tuple[BackupEntry, ...]:
        """Return backup metadata without opening the database files."""

        parsed_scope = TCCDatabaseScope(scope)
        entries: list[BackupEntry] = []
        for path in self.list_backups(parsed_scope):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append(
                BackupEntry(
                    path=path,
                    scope=parsed_scope,
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(
                        stat.st_mtime,
                    )
                    .astimezone()
                    .isoformat(timespec="seconds"),
                )
            )
        return tuple(entries)

    def is_managed_backup(
        self,
        backup_path: str | Path,
        scope: TCCDatabaseScope | str,
    ) -> bool:
        """Require restore sources to live in the managed scope directory."""

        parsed_scope = TCCDatabaseScope(scope)
        candidate = Path(backup_path).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
            directory = self.directory_for_scope(parsed_scope).resolve(strict=True)
        except OSError:
            return False
        return (
            resolved.is_file()
            and resolved.suffix == ".bak"
            and resolved.parent == directory
        )

    @staticmethod
    def _copy_database(source_path: Path, destination_path: Path) -> None:
        source: sqlite3.Connection | None = None
        destination: sqlite3.Connection | None = None
        try:
            source = sqlite3.connect(
                f"{source_path.as_uri()}?mode=ro",
                uri=True,
                timeout=2.0,
            )
            source.execute("PRAGMA query_only = ON")
            source.execute("PRAGMA busy_timeout = 2000")
            destination = sqlite3.connect(destination_path, timeout=2.0)
            source.backup(destination)
            check = destination.execute("PRAGMA quick_check").fetchone()
            if check is None or str(check[0]).casefold() != "ok":
                raise BackupError("备份文件完整性检查失败。")
            destination.commit()
        except sqlite3.Error as exc:
            raise BackupError(f"SQLite 备份失败：{exc}") from exc
        finally:
            if destination is not None:
                destination.close()
            if source is not None:
                source.close()

    @staticmethod
    def _reserve_backup_name(
        directory: Path,
        prefix: str,
        temporary_path: Path,
    ) -> Path:
        for index in range(1000):
            suffix = "" if index == 0 else f"-{index:03d}"
            candidate = directory / f"{prefix}{suffix}.bak"
            try:
                os.link(temporary_path, candidate)
            except FileExistsError:
                continue
            temporary_path.unlink(missing_ok=True)
            return candidate
        raise BackupError("无法为备份文件分配唯一名称。")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
