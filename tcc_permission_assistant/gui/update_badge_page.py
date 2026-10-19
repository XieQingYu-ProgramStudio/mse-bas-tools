"""System Settings update badge cleanup page."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
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
from tcc_permission_assistant.core.update_badge import (
    AttentionBadge,
    UpdateBadgeManager,
)
from tcc_permission_assistant.gui.components import (
    action_button,
    page_header,
    panel,
    section_title,
    show_error,
)


class UpdateBadgePage(QWidget):
    def __init__(
        self,
        audit: AuditLogger,
        manager: UpdateBadgeManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.audit = audit
        self.manager = manager or UpdateBadgeManager()
        self.items: tuple[AttentionBadge, ...] = ()
        self._item_by_row: dict[int, AttentionBadge] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(14)

        refresh_button = action_button("刷新", "refresh-cw")
        refresh_button.clicked.connect(self.refresh)
        header, _ = page_header(
            "更新提示",
            "只清理设置红点 · 不屏蔽安全更新",
            [refresh_button],
        )
        root.addWidget(header)

        status_panel, status_layout = panel()
        title_row = QHBoxLayout()
        title_row.addWidget(section_title("当前设置红点"))
        title_row.addStretch(1)
        self.status_label = QLabel("正在读取")
        self.status_label.setObjectName("muted")
        title_row.addWidget(self.status_label)
        status_layout.addLayout(title_row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["选择", "设置项", "分类"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._selection_changed)
        self.table.setMinimumHeight(190)
        status_layout.addWidget(self.table)
        root.addWidget(status_panel, 1)

        note = QFrame()
        note.setObjectName("warningBox")
        note_layout = QVBoxLayout(note)
        note_layout.setContentsMargins(14, 10, 14, 10)
        note_label = QLabel(
            "只清除视觉提示，不修改更新策略。系统再次检测到更新时，红点可能重新出现。"
        )
        note_label.setWordWrap(True)
        note_layout.addWidget(note_label)
        root.addWidget(note)

        action_row = QHBoxLayout()
        self.selection_label = QLabel("未选择")
        self.selection_label.setObjectName("muted")
        action_row.addWidget(self.selection_label)
        action_row.addStretch(1)
        self.clear_button = action_button(
            "清理所选红点",
            "bell-dot",
            role="primary",
        )
        self.clear_button.setEnabled(False)
        self.clear_button.clicked.connect(self.clear_selected)
        action_row.addWidget(self.clear_button)
        root.addLayout(action_row)

        restore_panel, restore_layout = panel()
        restore_layout.addWidget(section_title("红点状态备份"))
        restore_row = QHBoxLayout()
        self.backup_combo = QComboBox()
        self.backup_combo.setMinimumWidth(320)
        restore_row.addWidget(self.backup_combo, 1)
        self.restore_button = action_button("恢复所选状态", "archive-restore")
        self.restore_button.clicked.connect(self.restore_selected)
        restore_row.addWidget(self.restore_button)
        restore_layout.addLayout(restore_row)
        self.backup_path_label = QLabel(f"备份目录：{self.manager.backup_directory}")
        self.backup_path_label.setObjectName("mono")
        self.backup_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        restore_layout.addWidget(self.backup_path_label)
        root.addWidget(restore_panel)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        try:
            snapshot = self.manager.read()
        except Exception as exc:
            show_error(self, "无法读取设置红点", exc)
            return
        self.items = snapshot.items
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.items))
        self._item_by_row.clear()
        for row, item in enumerate(self.items):
            self._item_by_row[row] = item
            check = QTableWidgetItem()
            check.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
            )
            check.setCheckState(
                Qt.CheckState.Checked
                if item.is_update_related
                else Qt.CheckState.Unchecked
            )
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(item.bundle_id))
            self.table.setItem(row, 2, QTableWidgetItem(item.category))
            self.table.setRowHeight(row, 38)
        self.table.blockSignals(False)
        update_count = len(snapshot.update_items)
        self.status_label.setText(
            f"{len(self.items)} 个红点项目，其中 {update_count} 个与更新相关"
            if self.items
            else "当前没有设置红点"
        )
        self._refresh_backups()
        self._selection_changed()

    def _refresh_backups(self) -> None:
        self.backup_combo.clear()
        for path in self.manager.list_backups()[:20]:
            self.backup_combo.addItem(path.name, str(path))
        self.restore_button.setEnabled(self.backup_combo.count() > 0)

    def _selection_changed(self, _item=None) -> None:
        count = len(self.selected_keys())
        self.selection_label.setText(f"已选择 {count} 项" if count else "未选择")
        self.clear_button.setEnabled(count > 0)

    def selected_keys(self) -> tuple[str, ...]:
        return tuple(
            item.bundle_id
            for row, item in self._item_by_row.items()
            if (
                (check := self.table.item(row, 0)) is not None
                and check.checkState() == Qt.CheckState.Checked
            )
        )

    def clear_selected(self) -> None:
        keys = self.selected_keys()
        if not keys:
            return
        answer = QMessageBox.question(
            self,
            "清理设置红点",
            f"将清理 {len(keys)} 个设置红点项目。\n\n"
            "修改前会备份当前偏好，并在完成后刷新 System Settings 与 Dock。"
            "这不会修改系统更新策略。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self.manager.clear_badges(keys, restart_ui=True)
        except Exception as exc:
            show_error(self, "清理红点失败", exc)
            return
        self.audit.event(
            "clear_update_badge",
            keys=list(result.cleared_keys),
            backup_path=result.backup.path,
        )
        self.refresh()
        QMessageBox.information(
            self,
            "红点已清理",
            f"已清理 {len(result.cleared_keys)} 个红点项目。\n\n"
            f"备份：{result.backup.path}",
        )

    def restore_selected(self) -> None:
        backup_path = self.backup_combo.currentData()
        if not backup_path:
            return
        try:
            result = self.manager.restore(backup_path, restart_ui=True)
        except Exception as exc:
            show_error(self, "恢复红点状态失败", exc)
            return
        self.audit.event(
            "restore_update_badge",
            restored_from=result.restored_from,
            backup_path=result.pre_restore_backup.path,
        )
        self.refresh()
        QMessageBox.information(
            self,
            "红点状态已恢复",
            f"恢复前备份：{result.pre_restore_backup.path}",
        )
