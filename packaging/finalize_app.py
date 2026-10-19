"""Finalize macOS bundle identity and copy user-facing brand assets."""

from __future__ import annotations

import plistlib
import shutil
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: finalize_app.py APP_PATH VERSION")
    app_path = Path(sys.argv[1]).resolve()
    version = sys.argv[2]
    contents = app_path / "Contents"
    info_path = contents / "Info.plist"
    resources = contents / "Resources"
    resources.mkdir(parents=True, exist_ok=True)

    with info_path.open("rb") as file_handle:
        info = plistlib.load(file_handle)
    info.update(
        {
            "CFBundleDisplayName": "月星BAS工具箱",
            "CFBundleName": "月星BAS工具箱",
            "CFBundleIdentifier": "com.yuexing.bastoolbox",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "CFBundleGetInfoString": (f"月星BAS工具箱 {version} · 谢清宇@谢清宇工作室"),
            "CFBundleDevelopmentRegion": "zh_CN",
            "CFBundleIconFile": "AppIcon.icns",
            "LSApplicationCategoryType": "public.app-category.utilities",
            "LSMinimumSystemVersion": "15.0",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "谢清宇工作室",
        }
    )
    with info_path.open("wb") as file_handle:
        plistlib.dump(info, file_handle, sort_keys=False)

    root = Path(__file__).resolve().parent.parent
    shutil.copy2(root / "packaging/AppIcon.icns", resources / "AppIcon.icns")
    shutil.copy2(
        root / "tcc_permission_assistant/gui/assets/xieqingyu-studio-logo.png",
        resources / "StudioLogo.png",
    )
    print(info_path)


if __name__ == "__main__":
    main()
