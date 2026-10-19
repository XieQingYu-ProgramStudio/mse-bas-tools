"""Lucide icon loading with on-demand tinting."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap

from tcc_permission_assistant.gui.theme import COLORS

ICON_DIRECTORY = Path(__file__).with_name("icons")


@lru_cache(maxsize=128)
def load_icon(
    name: str,
    color: str = COLORS["muted"],
    size: int = 18,
) -> QIcon:
    path = ICON_DIRECTORY / f"{name}.svg"
    if not path.is_file():
        return QIcon()
    source = QPixmap(str(path))
    if source.isNull():
        return QIcon()
    scaled = source.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    tinted = QPixmap(scaled.size())
    tinted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, scaled)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(color))
    painter.end()
    return QIcon(tinted)
