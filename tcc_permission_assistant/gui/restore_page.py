"""Managed backup browser and confirmed restore page."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tcc_permission_assistant.core.backup import BackupManager
from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.core.models import (
    BackupEntry,
    RestorePlan,
    TCCDatabaseScope,
)
from tcc_permission_assistant.core.restore import (
    SYSTEM_RESTORE_PHRASE,
    USER_RESTORE_PHRASE,
    RestoreConfirmation,
    build_restore_plan,
    execute_restore,
)
from tcc_permission_assistant.gui.components import (
    DangerousConfirmationDialog,
    action_button,
    page_header,
    panel,
    section_title,
    show_error,
    status_badge,
)


class RestorePage(QWidget):
    environment_changed = pyqtSignal()

    def __init__(self, audit: AuditLogger, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.audit = audit
        self.manager = BackupManager()
        self.entries: tuple[BackupEntry, ...] = ()
        self.current_plan: RestorePlan | None = None
        self._build_ui()
        self.refresh_backups()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(14)

        refresh_button = action_button("刷新备份", "refresh-cw")
        refresh_button.clicked.connect(self.refresh_backups)
        header, _ = page_header(
            "恢复",
            "受管理备份 · 默认 dry-run",
            [refresh_button],
        )
        root.addWidget(header)

        scope_panel, scope_layout = panel()
        scope_row = QHBoxLayout()
        scope_label = QLabel("数据库作用域")
        scope_label.setObjectName("value")
        scope_row.addWidget(scope_label)
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("用户级", TCCDatabaseScope.USER.value)
        self.scope_combo.addItem("系统级", TCCDatabaseScope.SYSTEM.value)
        self.scope_combo.currentIndexChanged.connect(self._scope_changed)
        scope_row.addWidget(self.scope_combo)
        self.advanced_checkbox = QCheckBox("允许系统级高级操作")
        self.advanced_checkbox.setVisible(False)
        self.advanced_checkbox.toggled.connect(self.refresh_backups)
        scope_row.addWidget(self.advanced_checkbox)
        scope_row.addStretch(1)
        self.scope_badge = status_badge("用户级", "accent")
        scope_row.addWidget(self.scope_badge)
        scope_layout.addLayout(scope_row)
        root.addWidget(scope_panel)

        table_panel, table_layout = panel()
        table_header = QHBoxLayout()
        table_header.addWidget(section_title("可用备份"))
        table_header.addStretch(1)
        self.count_label = QLabel("0 个")
        self.count_label.setObjectName("muted")
        table_header.addWidget(self.count_label)
        table_layout.addLayout(table_header)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["修改时间", "作用域", "文件大小", "备份文件"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.setMinimumHeight(260)
        table_layout.addWidget(self.table)
        root.addWidget(table_panel, 1)

        preview_panel, preview_layout = panel()
        preview_layout.addWidget(section_title("恢复计划"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("选择一个备份以查看目标路径。")
        self.preview.setMaximumHeight(105)
        preview_layout.addWidget(self.preview)
        root.addWidget(preview_panel)

        options = QHBoxLayout()
        self.dry_run_checkbox = QCheckBox("仅预览恢复计划（dry-run）")
        self.dry_run_checkbox.setChecked(True)
        self.dry_run_checkbox.toggled.connect(self._mode_changed)
        options.addWidget(self.dry_run_checkbox)
        options.addStretch(1)
        self.restore_button = action_button(
            "预览恢复",
            "archive-restore",
            role="primary",
        )
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self.restore_selected)
        options.addWidget(self.restore_button)
        root.addLayout(options)

    def _scope(self) -> TCCDatabaseScope:
        return TCCDatabaseScope(self.scope_combo.currentData())

    def _scope_changed(self) -> None:
        scope = self._scope()
        is_system = scope is TCCDatabaseScope.SYSTEM
        self.advanced_checkbox.setVisible(is_system)
        if not is_system:
            self.advanced_checkbox.setChecked(False)
        self.scope_badge.setText("系统级" if is_system else "用户级")
        self.refresh_backups()

    def refresh_backups(self) -> None:
        scope = self._scope()
        if scope is TCCDatabaseScope.SYSTEM and not self.advanced_checkbox.isChecked():
            self.entries = ()
            self.table.setRowCount(0)
            self.count_label.setText("需要高级模式")
            self.preview.clear()
            self.restore_button.setEnabled(False)
            return
        try:
            self.entries = self.manager.list_backup_entries(scope)
        except Exception as exc:
            show_error(self, "无法读取备份列表", exc)
            return
        self.table.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            self.table.setItem(row, 0, QTableWidgetItem(entry.modified_at))
            self.table.setItem(
                row,
                1,
                QTableWidgetItem(
                    "系统级" if entry.scope is TCCDatabaseScope.SYSTEM else "用户级"
                ),
            )
            size_text = f"{entry.size_bytes:,} 字节"
            self.table.setItem(row, 2, QTableWidgetItem(size_text))
            self.table.setItem(row, 3, QTableWidgetItem(str(entry.path)))
            self.table.setRowHeight(row, 38)
        self.count_label.setText(f"{len(self.entries)} 个")
        self.preview.clear()
        self.restore_button.setEnabled(False)
        self.current_plan = None

    def _selected_entry(self) -> BackupEntry | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        if index < 0 or index >= len(self.entries):
            return None
        return self.entries[index]

    def _selection_changed(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            self.current_plan = None
            self.restore_button.setEnabled(False)
            self.preview.clear()
            return
        try:
            plan = build_restore_plan(
                entry.path,
                entry.scope,
                backup_manager=self.manager,
            )
        except Exception as exc:
            self.current_plan = None
            self.restore_button.setEnabled(False)
            show_error(self, "备份不可用", exc)
            return
        self.current_plan = plan
        self.preview.setPlainText(
            f"备份文件：{plan.backup_path}\n"
            f"目标数据库：{plan.target_path}\n"
            f"恢复前备份当前数据库："
            f"{'是' if plan.current_database_exists else '否'}"
        )
        self.restore_button.setEnabled(True)

    def _mode_changed(self, dry_run: bool) -> None:
        self.restore_button.setText("预览恢复" if dry_run else "恢复数据库")
        self.restore_button.setObjectName("primary" if dry_run else "danger")
        self.restore_button.style().unpolish(self.restore_button)
        self.restore_button.style().polish(self.restore_button)

    def restore_selected(self) -> None:
        if self.current_plan is None:
            return
        plan = self.current_plan
        if self.dry_run_checkbox.isChecked():
            QMessageBox.information(
                self,
                "恢复计划",
                f"目标：{plan.target_path}\n\n当前为 dry-run，未备份、未恢复。",
            )
            return

        phrase = (
            SYSTEM_RESTORE_PHRASE
            if plan.scope is TCCDatabaseScope.SYSTEM
            else USER_RESTORE_PHRASE
        )
        details = (
            f"备份文件：{plan.backup_path}\n"
            f"目标数据库：{plan.target_path}\n"
            f"作用域：{plan.scope.value}\n"
            f"恢复前自动备份："
            f"{'是' if plan.current_database_exists else '否'}\n"
        )
        if plan.scope is TCCDatabaseScope.SYSTEM:
            details += "提权方式：osascript 管理员授权，不保存密码。\n"
        dialog = DangerousConfirmationDialog(
            parent=self,
            title="确认恢复 TCC 数据库",
            summary="将用所选备份覆盖目标数据库内容。",
            details=details,
            phrase=phrase,
            execute_text="备份当前数据库并恢复",
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        confirmation = RestoreConfirmation(
            applications_closed=dialog.applications_closed,
            phrase=dialog.entered_phrase,
        )
        try:
            result = execute_restore(
                plan,
                confirmation,
                backup_manager=self.manager,
            )
            self.audit.event(
                "gui_restore",
                scope=plan.scope.value,
                backup_path=plan.backup_path,
                target_path=plan.target_path,
                pre_restore_backup=(
                    result.pre_restore_backup.path
                    if result.pre_restore_backup is not None
                    else None
                ),
                verified=result.verified,
                command_returncode=result.external_returncode,
            )
        except Exception as exc:
            show_error(self, "恢复失败", exc)
            self.refresh_backups()
            return
        backup_text = (
            str(result.pre_restore_backup.path)
            if result.pre_restore_backup is not None
            else "目标数据库原先不存在"
        )
        QMessageBox.information(
            self,
            "恢复完成",
            f"恢复后验证成功。\n\n恢复前备份：{backup_text}\n\n"
            "请完全退出并重新打开相关应用；如仍异常，请重启系统。",
        )
        self.refresh_backups()
        self.environment_changed.emit()
