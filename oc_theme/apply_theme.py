"""CLI wrapper for installing the Xie Qingyu Studio OpenCanopy theme."""

from __future__ import annotations

import argparse
from pathlib import Path

from tcc_permission_assistant.core.opencore_theme import (
    OpenCoreThemeError,
    OpenCoreThemeManager,
)


def install_theme(
    oc_directory: Path,
    *,
    compatibility_confirmed: bool = False,
) -> Path:
    result = OpenCoreThemeManager().install(
        oc_directory,
        compatibility_confirmed=compatibility_confirmed,
    )
    return result.backup.path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "oc_directory",
        nargs="?",
        default="/Volumes/EFI/EFI/OC",
    )
    parser.add_argument(
        "--compatibility-confirmed",
        action="store_true",
        help="确认当前 OpenCore 与内置 OpenCanopy 驱动兼容",
    )
    args = parser.parse_args()
    oc_directory = Path(args.oc_directory)
    try:
        result = OpenCoreThemeManager().install(
            oc_directory,
            compatibility_confirmed=args.compatibility_confirmed,
        )
    except OpenCoreThemeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"theme={result.theme_target}")
    print(f"backup={result.backup.path}")


if __name__ == "__main__":
    main()
