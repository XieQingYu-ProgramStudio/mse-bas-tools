"""Resolve localized application display names."""

from __future__ import annotations

import locale
import re
import subprocess
from functools import lru_cache

from tcc_permission_assistant.core.settings import (
    LANGUAGE_EN,
    LANGUAGE_SYSTEM,
    LANGUAGE_ZH_HANS,
)


@lru_cache(maxsize=4)
def system_languages() -> tuple[str, ...]:
    """Return macOS preferred languages, falling back to the process locale."""

    try:
        completed = subprocess.run(
            ["/usr/bin/defaults", "read", "-g", "AppleLanguages"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        values = re.findall(r'"([^"]+)"', completed.stdout)
        if values:
            return tuple(values)
    except (OSError, subprocess.TimeoutExpired):
        pass
    value = locale.getlocale()[0]
    return (value,) if value else ("en",)


def language_preferences(language: str) -> tuple[str, ...]:
    if language == LANGUAGE_SYSTEM:
        return system_languages()
    if language == LANGUAGE_ZH_HANS:
        return ("zh-Hans-CN", "zh-Hans", "zh_CN", "zh")
    if language == LANGUAGE_EN:
        return ("en-US", "en-GB", "en")
    return system_languages()


def lproj_candidates(language: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for preference in language_preferences(language):
        normalized = preference.strip()
        canonical = normalized.replace("_", "-")
        variants = (
            normalized,
            normalized.replace("-", "_"),
            "-".join(canonical.split("-")[:2]),
            "_".join(canonical.split("-")[:2]),
            canonical.split("-", 1)[0],
        )
        for variant in variants:
            if variant and variant not in candidates:
                candidates.append(variant)
    if "Base" not in candidates:
        candidates.append("Base")
    return tuple(candidates)
