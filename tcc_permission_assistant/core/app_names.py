"""Resolve Chinese display names for installed application bundles."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path

from tcc_permission_assistant.core.models import AppScanResult

MDLS_PATH = "/usr/bin/mdls"
SPOTLIGHT_BATCH_SIZE = 100

COMMON_CHINESE_NAMES = {
    "com.apple.ActivityMonitor": "活动监视器",
    "com.apple.AddressBook": "通讯录",
    "com.apple.AppStore": "App Store",
    "com.apple.Chess": "国际象棋",
    "com.apple.Console": "控制台",
    "com.apple.Dictionary": "词典",
    "com.apple.DiskUtility": "磁盘工具",
    "com.apple.FaceTime": "FaceTime 通话",
    "com.apple.FontBook": "字体册",
    "com.apple.Maps": "地图",
    "com.apple.MobileSMS": "信息",
    "com.apple.Music": "音乐",
    "com.apple.Notes": "备忘录",
    "com.apple.Photos": "照片",
    "com.apple.Preview": "预览",
    "com.apple.Safari": "Safari 浏览器",
    "com.apple.SystemProfiler": "系统信息",
    "com.apple.Terminal": "终端",
    "com.apple.TextEdit": "文本编辑",
    "com.apple.TV": "视频",
    "com.apple.VoiceMemos": "语音备忘录",
    "com.apple.backup.launcher": "时间机器",
    "com.apple.calculator": "计算器",
    "com.apple.clock": "时钟",
    "com.apple.finder": "访达",
    "com.apple.iCal": "日历",
    "com.apple.mail": "邮件",
    "com.apple.news": "新闻",
    "com.apple.podcasts": "播客",
    "com.apple.reminders": "提醒事项",
    "com.apple.shortcuts": "快捷指令",
    "com.apple.stocks": "股市",
    "com.apple.systempreferences": "系统设置",
    "com.apple.weather": "天气",
    "com.bytedance.lark": "飞书",
    "com.tencent.xinWeChat": "微信",
}


def chinese_app_names(
    results: Iterable[AppScanResult],
) -> dict[str, str]:
    """Return Chinese names keyed by Bundle ID, using Spotlight and safe fallbacks."""

    app_results = tuple(results)
    spotlight_names = spotlight_display_names(
        tuple(result.path for result in app_results)
    )
    names: dict[str, str] = {}
    for result in app_results:
        spotlight_name = spotlight_names.get(result.path, "").strip()
        if _contains_cjk(spotlight_name):
            display_name = spotlight_name
        elif result.bundle_id in COMMON_CHINESE_NAMES:
            display_name = COMMON_CHINESE_NAMES[result.bundle_id]
        elif _contains_cjk(result.name):
            display_name = result.name
        else:
            display_name = spotlight_name or result.name
        names[result.bundle_id] = display_name
    return names


def spotlight_display_names(paths: Sequence[Path]) -> dict[Path, str]:
    """Read localized Spotlight display names in batches."""

    names: dict[Path, str] = {}
    for offset in range(0, len(paths), SPOTLIGHT_BATCH_SIZE):
        batch = tuple(paths[offset : offset + SPOTLIGHT_BATCH_SIZE])
        command = [
            MDLS_PATH,
            "-name",
            "kMDItemDisplayName",
            "-raw",
            *(str(path) for path in batch),
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode != 0:
            continue
        names.update(
            parse_spotlight_display_names(
                completed.stdout.decode("utf-8", errors="replace"),
                batch,
            )
        )
    return names


def parse_spotlight_display_names(
    output: str,
    paths: Sequence[Path],
) -> dict[Path, str]:
    """Map NUL-separated ``mdls -raw`` output back to bundle paths."""

    values = output.split("\x00")
    if len(values) < len(paths):
        return {}
    return {
        path: value.strip()
        for path, value in zip(paths, values, strict=False)
        if value.strip() and value.strip() != "(null)"
    }


def _contains_cjk(value: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in value)
