"""Install the Xie Qingyu Studio OpenCanopy theme into a mounted EFI."""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from tcc_permission_assistant.core.backup import default_backup_root

ROOT = Path(__file__).resolve().parent
THEME_SOURCE = ROOT / "XieQingyu/Studio"
LABEL_SOURCE = ROOT / "Label"
DRIVER_SOURCE = ROOT / "OpenCanopy.efi"
THEME_VARIANT = r"XieQingyu\Studio"


def main() -> None:
    oc_directory = Path(sys.argv[1] if len(sys.argv) > 1 else "/Volumes/EFI/EFI/OC")
    install_theme(oc_directory)


def install_theme(oc_directory: Path) -> Path:
    oc_directory = oc_directory.resolve()
    config_path = oc_directory / "config.plist"
    if not config_path.is_file():
        raise SystemExit(f"找不到 OpenCore 配置：{config_path}")
    for source in (THEME_SOURCE, LABEL_SOURCE, DRIVER_SOURCE):
        if not source.exists():
            raise SystemExit(f"主题资源不完整：{source}")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = default_backup_root() / "OpenCore" / f"XieQingyuStudio-{timestamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(config_path, backup / "config.plist")
    shutil.copy2(
        config_path,
        oc_directory / f"config.plist.xieqingyu-{timestamp}",
    )
    shutil.copytree(oc_directory / "Resources/Label", backup / "Label")
    current_driver = oc_directory / "Drivers/OpenCanopy.efi"
    if current_driver.exists():
        shutil.copy2(current_driver, backup / "OpenCanopy.efi")
    theme_target = oc_directory / "Resources/Image/XieQingyu/Studio"
    if theme_target.exists():
        shutil.copytree(
            theme_target,
            backup / "Image-XieQingyu-Studio",
        )

    shutil.copytree(THEME_SOURCE, theme_target, dirs_exist_ok=True)
    label_target = oc_directory / "Resources/Label"
    for item in LABEL_SOURCE.iterdir():
        if item.is_file():
            shutil.copy2(item, label_target / item.name)
    shutil.copy2(DRIVER_SOURCE, current_driver)

    with config_path.open("rb") as file_handle:
        config = plistlib.load(file_handle)
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
    with config_path.open("wb") as file_handle:
        plistlib.dump(config, file_handle, sort_keys=False)

    lint = subprocess.run(
        ["/usr/bin/plutil", "-lint", str(config_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if lint.returncode != 0:
        raise SystemExit(lint.stdout + lint.stderr)
    (backup / "RESTORE.txt").write_text(
        "将本目录中的 config.plist 复制回 EFI/OC/config.plist，"
        "将 Label 复制回 EFI/OC/Resources/Label。"
        "如果安装前没有 OpenCanopy.efi，请删除后来安装的驱动。\n",
        encoding="utf-8",
    )
    print(f"theme={theme_target}")
    print(f"backup={backup}")
    return backup


if __name__ == "__main__":
    main()
