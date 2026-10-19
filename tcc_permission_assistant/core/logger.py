"""Privacy-conscious audit logging for commands and TCC operations."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "administrator_password",
}
_AUDIT_LOGGER: AuditLogger | None = None


def default_log_path(home: Path | None = None) -> Path:
    override = os.environ.get("TCC_ASSISTANT_LOG_PATH")
    if override:
        return Path(override).expanduser()
    return (
        (home or Path.home())
        / "Library"
        / "Application Support"
        / "TCCPermissionAssistant"
        / "Logs"
        / "audit.log"
    )


class AuditLogger:
    """Append JSON-lines audit events without storing personal file content."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        home: Path | None = None,
    ) -> None:
        self.path = Path(path or default_log_path(home)).expanduser()
        self.home = home or Path.home()

    def event(self, name: str, **fields: Any) -> None:
        """Append one event; logging failure never blocks a main operation."""

        payload = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": name,
        }
        for key, value in fields.items():
            if key.casefold() in _SENSITIVE_KEYS:
                continue
            payload[key] = _sanitize_value(value, self.home)
        try:
            parent_created = not self.path.parent.exists()
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if parent_created:
                os.chmod(self.path.parent, 0o700)
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            with os.fdopen(descriptor, "a", encoding="utf-8") as file_handle:
                file_handle.write(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
                )
            os.chmod(self.path, 0o600)
        except OSError:
            logging.getLogger(__name__).warning("无法写入审计日志。")

    def read_events(self) -> tuple[dict[str, Any], ...]:
        if not self.path.is_file():
            return ()
        events: list[dict[str, Any]] = []
        try:
            with self.path.open(encoding="utf-8") as file_handle:
                for line in file_handle:
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict):
                        events.append(value)
        except OSError:
            return ()
        return tuple(events)

    def clear(self) -> None:
        try:
            parent_created = not self.path.parent.exists()
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if parent_created:
                os.chmod(self.path.parent, 0o700)
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            os.close(descriptor)
            os.chmod(self.path, 0o600)
        except OSError:
            logging.getLogger(__name__).warning("无法清空审计日志。")


def configure_logging(
    verbose: bool = False,
    *,
    audit_path: str | Path | None = None,
) -> AuditLogger:
    """Configure stderr logging and return the persistent audit logger."""

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    global _AUDIT_LOGGER
    _AUDIT_LOGGER = AuditLogger(audit_path)
    return _AUDIT_LOGGER


def get_audit_logger() -> AuditLogger:
    global _AUDIT_LOGGER
    if _AUDIT_LOGGER is None:
        _AUDIT_LOGGER = AuditLogger()
    return _AUDIT_LOGGER


def redact_path(path: str | Path, home: Path | None = None) -> str:
    """Replace the current home directory prefix in user-facing log text."""

    home_path = home or Path.home()
    try:
        relative = Path(path).expanduser().resolve().relative_to(home_path.resolve())
    except (OSError, ValueError):
        return str(path)
    return str(Path("~") / relative)


def _sanitize_value(value: Any, home: Path) -> Any:
    if isinstance(value, Path):
        return redact_path(value, home)
    if isinstance(value, str):
        home_text = str(home)
        return value.replace(home_text, "~")
    if isinstance(value, dict):
        return {
            str(key): _sanitize_value(item, home)
            for key, item in value.items()
            if str(key).casefold() not in _SENSITIVE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item, home) for item in value]
    return value
