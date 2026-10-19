# 谢清宇工作室 OpenCore 主题

主题名称：`XieQingyu\Studio`

## 安装

EFI 分区挂载后执行：

```bash
cd /path/to/month-star-bas-toolbox
PYTHONPATH=. .venv/bin/python oc_theme/apply_theme.py "/Volumes/EFI/EFI/OC"
```

源码仓库不附带 `OpenCanopy.efi` 二进制。安装前请从 OpenCore 官方发行包中取得
与当前 OpenCore 版本匹配的 `OpenCanopy.efi`，放到：

```text
oc_theme/OpenCanopy.efi
```

该文件属于 OpenCorePkg，使用和分发时应遵守其 BSD-3-Clause 许可证。

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

最近一次备份路径会在安装脚本输出中显示。恢复时：

1. 将备份目录内的 `config.plist` 复制回 `EFI/OC/config.plist`；
2. 将备份的 `Label` 目录复制回 `EFI/OC/Resources/Label`；
3. 如果安装前没有 `OpenCanopy.efi`，删除后来安装的驱动；
4. 对恢复后的 `config.plist` 执行 `plutil -lint`。

安装前配置备份也会放在 EFI 的 `OC` 目录中，文件名以
`config.plist.xieqingyu-` 开头。

## 风险

引导界面改动无法在当前 macOS 会话中完整测试。首次重启前应保留可启动的
OpenCore 备份或救援 U 盘。主题不会修改 kext、ACPI、SIP、AMFI 或 SMBIOS。
