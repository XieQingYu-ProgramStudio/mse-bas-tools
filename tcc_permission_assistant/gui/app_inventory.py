"""Background scanner for installed application bundles."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.core.models import AppScanResult
from tcc_permission_assistant.core.scanner import AppScanner
from tcc_permission_assistant.core.settings import LANGUAGE_SYSTEM

DEFAULT_APP_DIRECTORIES = (
    Path("/Applications"),
    Path("/Applications/Utilities"),
    Path("/System/Applications"),
    Path("/System/Applications/Utilities"),
    Path.home() / "Applications",
)


def discover_app_bundles(
    directories: tuple[Path, ...] = DEFAULT_APP_DIRECTORIES,
) -> tuple[Path, ...]:
    """Return immediate .app bundles from common installation directories."""

    bundles: dict[Path, None] = {}
    for directory in directories:
        try:
            children = directory.iterdir()
        except OSError:
            continue
        for child in children:
            if child.suffix.casefold() != ".app":
                continue
            try:
                if not child.is_dir():
                    continue
                resolved = child.resolve()
            except OSError:
                continue
            bundles.setdefault(resolved, None)
    return tuple(sorted(bundles, key=lambda path: path.name.casefold()))


class AppInventoryWorker(QThread):
    """Scan installed bundles without blocking the Qt event loop."""

    progress = pyqtSignal(int, int, str)
    loaded = pyqtSignal(object)

    def __init__(
        self,
        audit: AuditLogger,
        display_language: str = LANGUAGE_SYSTEM,
        directories: tuple[Path, ...] = DEFAULT_APP_DIRECTORIES,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.audit = audit
        self.display_language = display_language
        self.directories = directories

    def run(self) -> None:
        paths = discover_app_bundles(self.directories)
        scanner = AppScanner(
            audit_logger=self.audit,
            display_language=self.display_language,
        )
        results: dict[str, AppScanResult] = {}
        errors: list[tuple[Path, str]] = []
        total = len(paths)
        for index, path in enumerate(paths, start=1):
            if self.isInterruptionRequested():
                break
            self.progress.emit(index, total, path.name)
            try:
                result = scanner.scan(path)
                if ".helper" in result.bundle_id.casefold():
                    continue
                results.setdefault(result.bundle_id, result)
            except Exception as exc:
                errors.append((path, str(exc)))
        self.loaded.emit(
            (
                tuple(
                    sorted(
                        results.values(),
                        key=lambda result: result.name.casefold(),
                    )
                ),
                tuple(errors),
            )
        )
