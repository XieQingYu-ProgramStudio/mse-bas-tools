"""GUI for applying and restoring the Xie Qingyu Studio OpenCanopy theme."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
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

from tcc_permission_assistant.core.efi import EFIManager
from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.core.opencore_theme import (
    OPEN_CANOPY_TARGET_VERSION,
    OpenCoreThemeManager,
    ThemeBackupInfo,
)
from tcc_permission_assistant.gui.components import (
    TaskThread,
    action_button,
    page_header,
    panel,
    section_title,
    show_error,
)


class OpenCoreThemePage(QWidget):
    open_efi_page_requested = pyqtSignal()

    def __init__(
        self,
        audit: AuditLogger,
        manager: OpenCoreThemeManager | None = None,
        efi_manager: EFIManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.audit = audit
        self.manager = manager or OpenCoreThemeManager()
        self.efi_manager = efi_manager or EFIManager()
        self.backups: tuple[ThemeBackupInfo, ...] = ()
        self._operation_worker: TaskThread | None = None
        self._operation_kind = ""
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(13)

        refresh_button = action_button("刷新", "refresh-cw")
        refresh_button.clicked.connect(self.refresh)
        header, _ = page_header(
            "OpenCore 主题",
            "谢清宇工作室定制主题 · 自动备份与还原",
            [refresh_button],
        )
        root.addWidget(header)

        overview = QHBoxLayout()
        preview_panel, preview_layout = panel()
        preview_panel.setFixedWidth(360)
        preview_layout.addWidget(section_title("主题预览"))
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(326, 184)
        self.preview.setStyleSheet("background: #0A1728; border-radius: 5px;")
        preview_layout.addWidget(self.preview)
        overview.addWidget(preview_panel)

        action_panel, action_layout = panel()
        action_layout.addWidget(section_title("安装位置"))
        target_row = QHBoxLayout()
        self.target_combo = QComboBox()
        self.target_combo.setEditable(True)
        self.target_combo.setMinimumWidth(340)
        self.target_combo.lineEdit().setPlaceholderText("/Volumes/EFI/EFI/OC")
        target_row.addWidget(self.target_combo, 1)
        refresh_targets = action_button("刷新 EFI", "refresh-cw")
        refresh_targets.clicked.connect(self.refresh_targets)
        target_row.addWidget(refresh_targets)
        browse_button = action_button("选择文件夹", "folder-open")
        browse_button.clicked.connect(self.choose_oc_directory)
        target_row.addWidget(browse_button)
        action_layout.addLayout(target_row)

        help_row = QHBoxLayout()
        help_text = QLabel(
            "应用后会启用 External Picker，并安装主题、中文标签和 OpenCanopy 驱动。"
        )
        help_text.setObjectName("muted")
        help_text.setWordWrap(True)
        help_row.addWidget(help_text, 1)
        efi_button = action_button("管理 EFI 分区", "hard-drive")
        efi_button.clicked.connect(self.open_efi_page_requested.emit)
        help_row.addWidget(efi_button)
        action_layout.addLayout(help_row)

        self.compatibility_checkbox = QCheckBox(
            f"已确认当前 OpenCore 与内置驱动兼容（目标 {OPEN_CANOPY_TARGET_VERSION}）"
        )
        self.compatibility_checkbox.toggled.connect(self._update_apply_state)
        action_layout.addWidget(self.compatibility_checkbox)

        apply_row = QHBoxLayout()
        self.status_label = QLabel("请选择已挂载的 EFI/OC")
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        apply_row.addWidget(self.status_label, 1)
        self.apply_button = action_button(
            "应用主题",
            "monitor",
            role="primary",
        )
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_theme)
        apply_row.addWidget(self.apply_button)
        action_layout.addLayout(apply_row)
        overview.addWidget(action_panel, 1)
        root.addLayout(overview)

        warning = QFrame()
        warning.setObjectName("warningBox")
        warning_layout = QVBoxLayout(warning)
        warning_layout.setContentsMargins(14, 10, 14, 10)
        warning_text = QLabel(
            "主题会修改 EFI/OC 中的 config.plist、Resources/Label 与 Drivers。"
            "操作前会自动备份，但仍建议保留可启动的 OpenCore 备份或救援 U 盘。"
        )
        warning_text.setWordWrap(True)
        warning_layout.addWidget(warning_text)
        root.addWidget(warning)

        backup_panel, backup_layout = panel()
        backup_header = QHBoxLayout()
        backup_header.addWidget(section_title("主题备份"))
        backup_header.addStretch(1)
        self.backup_count = QLabel("0 个")
        self.backup_count.setObjectName("muted")
        backup_header.addWidget(self.backup_count)
        self.restore_button = action_button(
            "还原所选备份",
            "archive-restore",
        )
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self.restore_selected)
        backup_header.addWidget(self.restore_button)
        backup_layout.addLayout(backup_header)

        self.backup_table = QTableWidget(0, 4)
        self.backup_table.setHorizontalHeaderLabels(
            ["创建时间", "原 OC 目录", "原主题", "原驱动"]
        )
        self.backup_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.backup_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.backup_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.backup_table.verticalHeader().setVisible(False)
        self.backup_table.setAlternatingRowColors(True)
        table_header = self.backup_table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.backup_table.itemSelectionChanged.connect(self._backup_selection_changed)
        backup_layout.addWidget(self.backup_table, 1)
        root.addWidget(backup_panel, 1)
        self._load_preview()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        self.refresh_targets()
        self.refresh_backups()

    def refresh_targets(self) -> None:
        current = self.target_combo.currentText().strip()
        candidates: list[Path] = []
        efi_error: str | None = None
        try:
            for partition in self.efi_manager.list_partitions():
                if partition.mount_point is None:
                    continue
                candidate = partition.mount_point / "EFI" / "OC"
                if (candidate / "config.plist").is_file():
                    candidates.append(candidate)
        except Exception as exc:
            efi_error = str(exc)

        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for candidate in candidates:
            self.target_combo.addItem(str(candidate), str(candidate))
        self.target_combo.setCurrentText(current)
        self.target_combo.blockSignals(False)
        if not current and candidates:
            self.target_combo.setCurrentIndex(0)
            current = str(candidates[0])

        if current:
            oc_directory = Path(current).expanduser()
            self.status_label.setText(f"目标：{oc_directory}")
        elif efi_error:
            self.status_label.setText(f"无法读取 EFI 分区：{efi_error}")
        else:
            self.status_label.setText(
                "未发现已挂载的 EFI/OC，请先挂载 EFI 或手动选择文件夹。"
            )

    def refresh_backups(self) -> None:
        try:
            self.backups = self.manager.list_backups()
        except Exception as exc:
            show_error(self, "无法读取主题备份", exc)
            self.backups = ()
        self.backup_table.setRowCount(len(self.backups))
        for row, backup in enumerate(self.backups):
            self.backup_table.setItem(
                row,
                0,
                QTableWidgetItem(backup.created_at.replace("T", " ")),
            )
            target_item = QTableWidgetItem(
                str(backup.oc_directory) if backup.oc_directory else "旧版备份"
            )
            target_item.setToolTip(str(backup.path))
            self.backup_table.setItem(row, 1, target_item)
            self.backup_table.setItem(
                row,
                2,
                QTableWidgetItem("已备份" if backup.had_theme else "无"),
            )
            self.backup_table.setItem(
                row,
                3,
                QTableWidgetItem("已备份" if backup.had_driver else "无"),
            )
            self.backup_table.setRowHeight(row, 38)
        self.backup_count.setText(f"{len(self.backups)} 个")
        self._backup_selection_changed()

    def choose_oc_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "选择 EFI/OC 文件夹",
            "/Volumes",
        )
        if path:
            self.target_combo.setEditText(path)
            self.status_label.setText(f"目标：{path}")

    def target_path(self) -> str:
        return self.target_combo.currentText().strip()

    def _update_apply_state(self, checked: bool) -> None:
        self.apply_button.setEnabled(checked)

    def apply_theme(self) -> None:
        target = self.target_path()
        if not self.compatibility_checkbox.isChecked():
            QMessageBox.warning(
                self,
                "未确认驱动兼容",
                "请先核对当前 OpenCore 版本与内置 OpenCanopy 驱动是否兼容。",
            )
            return
        if not target:
            QMessageBox.warning(
                self,
                "未选择 OC 目录",
                "请先挂载 EFI 并选择 EFI/OC 文件夹。",
            )
            return
        answer = QMessageBox.warning(
            self,
            "应用谢清宇工作室主题",
            f"目标：{target}\n\n"
            "将备份当前 config.plist、标签、主题和 OpenCanopy 驱动，"
            "然后写入新主题。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_operation(
            "apply",
            lambda: self.manager.install(
                target,
                compatibility_confirmed=True,
            ),
        )

    def _start_operation(self, kind: str, task) -> None:
        if self._operation_worker is not None:
            return
        self._operation_kind = kind
        self.apply_button.setEnabled(False)
        self.restore_button.setEnabled(False)
        self.compatibility_checkbox.setEnabled(False)
        self.status_label.setText(
            "正在应用主题，请勿拔出 EFI…"
            if kind == "apply"
            else "正在还原主题，请勿拔出 EFI…"
        )
        worker = TaskThread(task, self)
        worker.succeeded.connect(self._operation_succeeded)
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(self._operation_finished)
        self._operation_worker = worker
        worker.start()

    def _operation_succeeded(self, result: object) -> None:
        if self._operation_kind == "apply":
            self.audit.event(
                "apply_opencore_theme",
                oc_directory=str(result.config_path.parent),
                backup_path=result.backup.path,
            )
            self.status_label.setText("主题已应用，重新启动后可进入 OpenCanopy。")
            self.refresh_backups()
            QMessageBox.information(
                self,
                "主题已应用",
                f"主题目录：{result.theme_target}\n\n备份目录：{result.backup.path}",
            )
            return
        self.audit.event(
            "restore_opencore_theme",
            oc_directory=str(result.oc_directory),
            restored_backup=result.restored_backup.path,
            pre_restore_backup=result.pre_restore_backup.path,
        )
        self.status_label.setText("主题备份已还原。")
        self.refresh_backups()
        QMessageBox.information(
            self,
            "主题已还原",
            f"已恢复：{result.restored_backup.path}\n\n"
            f"还原前备份：{result.pre_restore_backup.path}",
        )

    def _operation_failed(self, error: object) -> None:
        title = (
            "应用 OpenCore 主题失败"
            if self._operation_kind == "apply"
            else "还原 OpenCore 主题失败"
        )
        show_error(self, title, error)
        self.status_label.setText(str(error))
        self.refresh_backups()

    def _operation_finished(self) -> None:
        worker = self._operation_worker
        if worker is not None:
            worker.deleteLater()
        self._operation_worker = None
        self.compatibility_checkbox.setEnabled(True)
        self._update_apply_state(self.compatibility_checkbox.isChecked())
        self._backup_selection_changed()

    def selected_backup(self) -> ThemeBackupInfo | None:
        rows = self.backup_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self.backups):
            return self.backups[row]
        return None

    def _backup_selection_changed(self) -> None:
        self.restore_button.setEnabled(self.selected_backup() is not None)

    def restore_selected(self) -> None:
        backup = self.selected_backup()
        if backup is None:
            return
        target = self.target_path() or (
            str(backup.oc_directory) if backup.oc_directory is not None else ""
        )
        answer = QMessageBox.warning(
            self,
            "还原 OpenCore 主题备份",
            f"备份时间：{backup.created_at}\n"
            f"目标：{target or '备份记录中的 OC 目录'}\n\n"
            "还原前会再备份当前主题状态。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_operation(
            "restore",
            lambda: self.manager.restore(
                backup.path,
                oc_directory=target or None,
            ),
        )

    def shutdown(self) -> None:
        worker = self._operation_worker
        if worker is not None and worker.isRunning():
            worker.wait()
        self._operation_worker = None

    def _load_preview(self) -> None:
        image_path = self.manager.theme_source / "Background.png"
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self.preview.setText("主题预览不可用")
            return
        self.preview.setPixmap(
            pixmap.scaled(
                326,
                184,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
