"""CLI wrapper for installing the Xie Qingyu Studio OpenCanopy theme."""

from __future__ import annotations

import sys
from pathlib import Path

from tcc_permission_assistant.core.opencore_theme import (
    OpenCoreThemeError,
    OpenCoreThemeManager,
)


def install_theme(oc_directory: Path) -> Path:
    result = OpenCoreThemeManager().install(oc_directory)
    return result.backup.path


def main() -> None:
    oc_directory = Path(sys.argv[1] if len(sys.argv) > 1 else "/Volumes/EFI/EFI/OC")
    try:
        result = OpenCoreThemeManager().install(oc_directory)
    except OpenCoreThemeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"theme={result.theme_target}")
    print(f"backup={result.backup.path}")


if __name__ == "__main__":
    main()
