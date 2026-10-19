"""Privacy-redacted audit log viewer."""

from __future__ import annotations

import json
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.gui.components import (
    action_button,
    page_header,
    panel,
    section_title,
)


class LogPage(QWidget):
    def __init__(self, audit: AuditLogger, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.audit = audit
        self.events: tuple[dict[str, Any], ...] = ()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(14)

        refresh_button = action_button("刷新", "refresh-cw")
        refresh_button.clicked.connect(self.refresh)
        copy_button = action_button("复制日志", "copy")
        copy_button.clicked.connect(self.copy_logs)
        clear_button = action_button("清空", "trash-2", role="danger")
        clear_button.clicked.connect(self.clear_logs)
        header, _ = page_header(
            "日志",
            "本机审计事件 · 已脱敏",
            [refresh_button, copy_button, clear_button],
        )
        root.addWidget(header)

        log_panel, log_layout = panel()
        header_row = QHBoxLayout()
        header_row.addWidget(section_title("审计事件"))
        header_row.addStretch(1)
        self.count_label = QLabel("0 条")
        self.count_label.setObjectName("muted")
        header_row.addWidget(self.count_label)
        log_layout.addLayout(header_row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["时间", "事件", "详情"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        table_header = self.table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        log_layout.addWidget(self.table, 1)

        self.path_label = QLabel(f"日志文件：{self.audit.path}")
        self.path_label.setObjectName("mono")
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        log_layout.addWidget(self.path_label)
        root.addWidget(log_panel, 1)

    def refresh(self) -> None:
        self.events = self.audit.read_events()
        self.table.setRowCount(len(self.events))
        for row, event in enumerate(reversed(self.events)):
            timestamp = str(event.get("timestamp", ""))
            name = str(event.get("event", ""))
            details = {
                key: value
                for key, value in event.items()
                if key not in {"timestamp", "event"}
            }
            detail_text = json.dumps(details, ensure_ascii=False, sort_keys=True)
            self.table.setItem(row, 0, QTableWidgetItem(timestamp))
            self.table.setItem(row, 1, QTableWidgetItem(name))
            self.table.setItem(row, 2, QTableWidgetItem(detail_text))
            self.table.setRowHeight(row, 34)
        self.count_label.setText(f"{len(self.events)} 条")

    def copy_logs(self) -> None:
        lines = [
            json.dumps(event, ensure_ascii=False, sort_keys=True)
            for event in self.events
        ]
        QApplication.clipboard().setText("\n".join(lines))
        QMessageBox.information(self, "已复制", "审计日志已复制到剪贴板。")

    def clear_logs(self) -> None:
        if not self.events:
            return
        answer = QMessageBox.question(
            self,
            "清空日志",
            "确定清空全部审计日志吗？此操作不会影响 TCC 数据库或备份。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        self.audit.clear()
        self.refresh()
