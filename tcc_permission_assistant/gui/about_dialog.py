"""Product and studio information dialog."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from tcc_permission_assistant import __version__
from tcc_permission_assistant.branding import (
    APP_NAME,
    DEVELOPER_NAME,
    PERMISSION_MODULE_NAME,
    SYSTEM_MODULE_NAME,
)
from tcc_permission_assistant.gui.components import action_button, status_badge

ASSET_DIRECTORY = Path(__file__).with_name("assets")


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("aboutDialog")
        self.setWindowTitle(f"关于 {APP_NAME}")
        self.setModal(True)
        self.setFixedSize(610, 470)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(38, 30, 38, 24)
        root.setSpacing(12)

        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("background: transparent;")
        source = QPixmap(str(ASSET_DIRECTORY / "xieqingyu-studio-logo.png"))
        if not source.isNull():
            logo.setPixmap(
                source.scaled(
                    430,
                    167,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        logo.setAccessibleName("谢清宇工作室 Logo")
        root.addWidget(logo)

        title_row = QHBoxLayout()
        title_row.addStretch(1)
        title = QLabel(APP_NAME)
        title.setObjectName("aboutProduct")
        title_row.addWidget(title)
        version = status_badge(f"版本 {__version__}", "accent")
        title_row.addWidget(version)
        title_row.addStretch(1)
        root.addLayout(title_row)

        caption = QLabel("macOS 本地工具")
        caption.setObjectName("muted")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(caption)

        divider = QFrame()
        divider.setObjectName("aboutDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(divider)

        developer = QLabel(f"开发者：{DEVELOPER_NAME}")
        developer.setObjectName("aboutDeveloper")
        developer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        developer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(developer)

        modules = QLabel(f"{PERMISSION_MODULE_NAME} · {SYSTEM_MODULE_NAME}")
        modules.setObjectName("muted")
        modules.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(modules)
        root.addStretch(1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = action_button("关闭", role="primary")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        root.addLayout(button_row)
