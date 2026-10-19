"""Reusable widgets and dialogs for the desktop interface."""

from __future__ import annotations

from collections.abc import Iterable

from PyQt6.QtCore import QRectF, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tcc_permission_assistant.gui.icons import load_icon
from tcc_permission_assistant.gui.theme import COLORS


def page_header(
    title: str,
    subtitle: str,
    actions: Iterable[QWidget] = (),
) -> tuple[QWidget, QHBoxLayout]:
    wrapper = QWidget()
    layout = QHBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    text_layout = QVBoxLayout()
    text_layout.setSpacing(3)
    title_label = QLabel(title)
    title_label.setObjectName("pageTitle")
    subtitle_label = QLabel(subtitle)
    subtitle_label.setObjectName("pageSubtitle")
    subtitle_label.setWordWrap(True)
    text_layout.addWidget(title_label)
    text_layout.addWidget(subtitle_label)
    layout.addLayout(text_layout, 1)
    for action in actions:
        layout.addWidget(action, 0, Qt.AlignmentFlag.AlignVCenter)
    return wrapper, layout


def action_button(
    text: str,
    icon_name: str | None = None,
    *,
    role: str = "default",
    tooltip: str | None = None,
) -> QPushButton:
    button = QPushButton(text)
    if icon_name:
        button.setIcon(
            load_icon(
                icon_name,
                "#FFFFFF" if role in {"primary", "danger"} else COLORS["muted"],
                17,
            )
        )
    if role != "default":
        button.setObjectName(role)
    if tooltip:
        button.setToolTip(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def section_title(text: str, detail: str | None = None) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    layout.addWidget(label)
    if detail:
        detail_label = QLabel(detail)
        detail_label.setObjectName("muted")
        layout.addWidget(detail_label)
    layout.addStretch(1)
    return widget


def status_badge(text: str, state: str = "none") -> QLabel:
    badge = QLabel(text)
    badge.setProperty("badge", state)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setSizePolicy(
        QSizePolicy.Policy.Maximum,
        QSizePolicy.Policy.Fixed,
    )
    return badge


def panel() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    return frame, layout


def mono_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("mono")
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


def show_error(parent: QWidget, title: str, error: object) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(title)
    box.setInformativeText(str(error))
    box.exec()


class DangerousConfirmationDialog(QDialog):
    """One review dialog combining exit confirmation and typed phrase."""

    def __init__(
        self,
        *,
        parent: QWidget | None,
        title: str,
        summary: str,
        details: str,
        phrase: str,
        execute_text: str = "确认执行",
        closed_text: str = "我已确认相关应用已经完全退出",
    ) -> None:
        super().__init__(parent)
        self.phrase = phrase
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(720, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        summary_label = QLabel(summary)
        summary_label.setObjectName("muted")
        summary_label.setWordWrap(True)
        layout.addWidget(summary_label)

        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(details)
        font = QFont("SF Mono")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(11)
        preview.setFont(font)
        layout.addWidget(preview, 1)

        warning = QLabel(
            "这是数据库写入操作。请确认相关应用已完全退出，并核对目标路径和 SQL。"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            f"color: {COLORS['danger']}; "
            f"background: {COLORS['danger_soft']}; "
            "border: 1px solid #E8C2BE; border-radius: 6px; padding: 9px;"
        )
        layout.addWidget(warning)

        self.closed_checkbox = QCheckBox(closed_text)
        layout.addWidget(self.closed_checkbox)

        phrase_row = QHBoxLayout()
        phrase_label = QLabel(f"输入 {phrase} 以确认")
        self.phrase_input = QLineEdit()
        self.phrase_input.setPlaceholderText(phrase)
        self.phrase_input.setMaximumWidth(220)
        phrase_row.addWidget(phrase_label)
        phrase_row.addStretch(1)
        phrase_row.addWidget(self.phrase_input)
        layout.addLayout(phrase_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = action_button("取消")
        self.confirm_button = action_button(
            execute_text,
            role="danger",
        )
        self.confirm_button.setEnabled(False)
        button_row.addWidget(cancel_button)
        button_row.addWidget(self.confirm_button)
        layout.addLayout(button_row)

        cancel_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self.accept)
        self.closed_checkbox.toggled.connect(self._update_confirm_state)
        self.phrase_input.textChanged.connect(self._update_confirm_state)

    @property
    def applications_closed(self) -> bool:
        return self.closed_checkbox.isChecked()

    @property
    def entered_phrase(self) -> str:
        return self.phrase_input.text()

    def _update_confirm_state(self) -> None:
        self.confirm_button.setEnabled(
            self.closed_checkbox.isChecked()
            and self.phrase_input.text().strip() == self.phrase
        )


class ToggleSwitch(QAbstractButton):
    """Compact two-state switch for immediate settings."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        accessible_name: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if accessible_name:
            self.setAccessibleName(accessible_name)

    def sizeHint(self) -> QSize:
        return QSize(46, 26)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track = QRectF(2, 3, 42, 20)
        if not self.isEnabled():
            track_color = QColor(COLORS["surface_alt"])
            border_color = QColor(COLORS["line"])
        elif self.isChecked():
            track_color = QColor(COLORS["accent"])
            border_color = QColor(COLORS["accent"])
        else:
            track_color = QColor("#E5EBED")
            border_color = QColor("#B8C4C9")
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, 10, 10)

        knob_x = 24 if self.isChecked() else 4
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(knob_x, 5, 16, 16))

        if self.hasFocus():
            painter.setPen(QPen(QColor(COLORS["accent"]), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(0.75, 1.75, 44.5, 22.5), 11, 11)


class TaskThread(QThread):
    """Run one callable without blocking the Qt event loop."""

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, task, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._task = task

    def run(self) -> None:
        try:
            result = self._task()
        except Exception as exc:
            self.failed.emit(exc)
            return
        self.succeeded.emit(result)
