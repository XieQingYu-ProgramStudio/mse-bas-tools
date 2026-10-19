"""Persistent application settings."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from tcc_permission_assistant.core.backup import default_backup_root

LANGUAGE_SYSTEM = "system"
LANGUAGE_ZH_HANS = "zh-Hans"
LANGUAGE_EN = "en"
SUPPORTED_APP_NAME_LANGUAGES = (
    LANGUAGE_SYSTEM,
    LANGUAGE_ZH_HANS,
    LANGUAGE_EN,
)


def default_settings_path(home: Path | None = None) -> Path:
    return default_backup_root(home).parent / "settings.json"


@dataclass(frozen=True, slots=True)
class SettingsData:
    application_name_language: str = LANGUAGE_SYSTEM
    auto_clear_update_badges: bool = False
    launch_at_login: bool = False


class AppSettings:
    """Read and atomically persist local application settings."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or default_settings_path()).expanduser()
        self.data = self._load()

    @property
    def application_name_language(self) -> str:
        return self.data.application_name_language

    @property
    def auto_clear_update_badges(self) -> bool:
        return self.data.auto_clear_update_badges

    @property
    def launch_at_login(self) -> bool:
        return self.data.launch_at_login

    def set_application_name_language(self, language: str) -> None:
        if language not in SUPPORTED_APP_NAME_LANGUAGES:
            raise ValueError(f"不支持的应用名称语言：{language}")
        self.data = replace(self.data, application_name_language=language)
        self.save()

    def update_preferences(
        self,
        *,
        application_name_language: str,
        auto_clear_update_badges: bool,
        launch_at_login: bool,
    ) -> None:
        if application_name_language not in SUPPORTED_APP_NAME_LANGUAGES:
            raise ValueError(f"不支持的应用名称语言：{application_name_language}")
        self.data = SettingsData(
            application_name_language=application_name_language,
            auto_clear_update_badges=bool(auto_clear_update_badges),
            launch_at_login=bool(launch_at_login),
        )
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".settings-",
            suffix=".json",
            dir=self.path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file_handle:
                json.dump(asdict(self.data), file_handle, ensure_ascii=False, indent=2)
                file_handle.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _load(self) -> SettingsData:
        if not self.path.is_file():
            return SettingsData()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return SettingsData()
        language = (
            payload.get("application_name_language")
            if isinstance(payload, dict)
            else None
        )
        if language not in SUPPORTED_APP_NAME_LANGUAGES:
            language = LANGUAGE_SYSTEM
        auto_clear = payload.get("auto_clear_update_badges", False)
        launch_at_login = payload.get("launch_at_login", False)
        return SettingsData(
            application_name_language=language,
            auto_clear_update_badges=(
                auto_clear if isinstance(auto_clear, bool) else False
            ),
            launch_at_login=(
                launch_at_login if isinstance(launch_at_login, bool) else False
            ),
        )
