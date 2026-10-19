"""Per-user login item management through a LaunchAgent."""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

from tcc_permission_assistant.core.errors import TCCAssistantError

LAUNCH_AGENT_LABEL = "com.yuexing.bastoolbox.autostart"


class AutoStartError(TCCAssistantError):
    """A login item could not be installed or removed."""


class AutoStartManager:
    """Install a per-user LaunchAgent without administrator privileges."""

    def __init__(
        self,
        launch_agents_directory: str | Path | None = None,
        application_path: str | Path | None = None,
    ) -> None:
        self.launch_agents_directory = Path(
            launch_agents_directory or (Path.home() / "Library" / "LaunchAgents")
        ).expanduser()
        self.plist_path = self.launch_agents_directory / f"{LAUNCH_AGENT_LABEL}.plist"
        self.application_path = (
            Path(application_path).expanduser()
            if application_path is not None
            else self._bundled_application_path()
        )

    @property
    def is_enabled(self) -> bool:
        return self.plist_path.is_file()

    @property
    def availability_error(self) -> str | None:
        if self.application_path is None:
            return "自动启动只能在打包后的 .app 中使用。"
        if str(self.application_path).startswith("/Volumes/"):
            return "请先将应用拖入“应用程序”文件夹，再启用自动启动。"
        if self.application_path.suffix.casefold() != ".app":
            return "找不到可用的应用包路径。"
        executable = self.application_path / "Contents/MacOS"
        if not executable.is_dir():
            return "应用包结构不完整。"
        return None

    def enable(self) -> Path:
        if self.availability_error is not None or self.application_path is None:
            raise AutoStartError(self.availability_error or "当前环境不支持自动启动。")
        executable = next(
            self.application_path.joinpath("Contents/MacOS").iterdir(),
            None,
        )
        if executable is None:
            raise AutoStartError("应用包中没有可执行文件。")
        payload = {
            "Label": LAUNCH_AGENT_LABEL,
            "ProgramArguments": [str(executable)],
            "RunAtLoad": True,
            "KeepAlive": False,
            "LimitLoadToSessionType": "Aqua",
            "ProcessType": "Interactive",
        }
        try:
            self.launch_agents_directory.mkdir(parents=True, exist_ok=True)
            data = plistlib.dumps(payload, sort_keys=False)
            descriptor = os.open(
                self.plist_path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o644,
            )
            with os.fdopen(descriptor, "wb") as file_handle:
                file_handle.write(data)
        except OSError as exc:
            raise AutoStartError(f"写入登录启动项失败：{exc}") from exc
        return self.plist_path

    def disable(self) -> None:
        try:
            self.plist_path.unlink(missing_ok=True)
        except OSError as exc:
            raise AutoStartError(f"移除登录启动项失败：{exc}") from exc

    @staticmethod
    def _bundled_application_path() -> Path | None:
        if not getattr(sys, "frozen", False):
            return None
        executable = Path(sys.executable).resolve()
        bundle = executable.parents[2]
        return bundle if bundle.suffix.casefold() == ".app" else None
