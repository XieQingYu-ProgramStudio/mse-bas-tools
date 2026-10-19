"""Generate the square application icon from the studio brand asset."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QImage, QPainter

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "tcc_permission_assistant/gui/assets/xieqingyu-studio-logo.png"
OUTPUT = ROOT / "packaging/AppIcon-1024.png"


def main() -> None:
    source = QImage(str(SOURCE))
    if source.isNull():
        raise SystemExit(f"无法读取工作室 Logo：{SOURCE}")

    emblem = source.copy(20, 0, 780, 780).scaled(
        900,
        900,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QImage(
        1024,
        1024,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    x = (canvas.width() - emblem.width()) // 2
    y = (canvas.height() - emblem.height()) // 2
    painter.drawImage(QRect(x, y, emblem.width(), emblem.height()), emblem)
    painter.end()
    if not canvas.save(str(OUTPUT), "PNG"):
        raise SystemExit(f"无法写入应用图标：{OUTPUT}")
    print(OUTPUT)


if __name__ == "__main__":
    main()
