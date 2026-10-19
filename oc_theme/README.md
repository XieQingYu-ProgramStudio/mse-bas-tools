# 谢清宇工作室 OpenCore 主题

主题名称：`XieQingyu\Studio`

## 安装

### 图形界面

1. 在“系统维护 → EFI 分区”挂载 EFI；
2. 打开“系统维护 → OC 主题”；
3. 选择检测到的 `/Volumes/.../EFI/OC`，或手动选择目录；
4. 点击“应用主题”并确认。

应用失败时工具会自动回滚。主题备份保存在：

```text
~/Library/Application Support/TCCPermissionAssistant/Backups/OpenCore/
```

### 命令行

EFI 分区挂载后执行：

```bash
cd "$(git rev-parse --show-toplevel)"
PYTHONPATH=. .venv/bin/python oc_theme/apply_theme.py "/Volumes/EFI/EFI/OC"
```

命令行应用前还必须显式确认驱动兼容：

```bash
PYTHONPATH=. .venv/bin/python oc_theme/apply_theme.py \
  --compatibility-confirmed "/Volumes/EFI/EFI/OC"
```

安装脚本会：

- 备份 `config.plist` 和原始 `Resources/Label`；
- 备份安装前已有的同名主题和 OpenCanopy 驱动；
- 复制主题到 `Resources/Image/XieQingyu/Studio`；
- 复制中文标签到 `Resources/Label`；
- 安装匹配 OpenCore 1.0.9 的 OpenCanopy 驱动；
- 设置 `PickerMode=External`、`PickerVariant=XieQingyu\Studio`、
  `PickerAttributes=21`；
- 使用 `plutil -lint` 检查配置格式。

## 恢复

“OC 主题”页会列出工具管理的主题备份。选择备份后点击“还原所选备份”即可。
还原前会再保存当前状态，便于再次撤销。

也可以手动恢复：

1. 将备份目录内的 `config.plist` 复制回 `EFI/OC/config.plist`；
2. 将备份的 `Label` 目录复制回 `EFI/OC/Resources/Label`；
3. 如果安装前没有 `OpenCanopy.efi`，删除后来安装的驱动；
4. 对恢复后的 `config.plist` 执行 `plutil -lint`。

安装前配置备份也会放在 EFI 的 `OC` 目录中，文件名以
`config.plist.xieqingyu-` 开头。

开源仓库不附带 `OpenCanopy.efi` 时，请从 OpenCore 官方发行包获取匹配版本并
放到 `oc_theme/OpenCanopy.efi`。

## 风险

引导界面改动无法在当前 macOS 会话中完整测试。首次重启前应保留可启动的
OpenCore 备份或救援 U 盘。主题不会修改 kext、ACPI、SIP、AMFI 或 SMBIOS。
