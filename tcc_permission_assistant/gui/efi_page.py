"""EFI partition discovery, mount, and unmount page."""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
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

from tcc_permission_assistant.core.efi import EFIManager, EFIPartition
from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.gui.components import (
    action_button,
    page_header,
    panel,
    section_title,
    show_error,
    status_badge,
)


class EFIPage(QWidget):
    def __init__(
        self,
        audit: AuditLogger,
        manager: EFIManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.audit = audit
        self.manager = manager or EFIManager()
        self.partitions: tuple[EFIPartition, ...] = ()
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(14)

        refresh_button = action_button("刷新", "refresh-cw")
        refresh_button.clicked.connect(self.refresh)
        header, _ = page_header(
            "EFI 分区",
            "选择后挂载或卸载 · 不修改引导文件",
            [refresh_button],
        )
        root.addWidget(header)

        table_panel, table_layout = panel()
        title_row = QHBoxLayout()
        title_row.addWidget(section_title("EFI 分区列表"))
        title_row.addStretch(1)
        self.status_label = QLabel("正在读取")
        self.status_label.setObjectName("muted")
        title_row.addWidget(self.status_label)
        table_layout.addLayout(title_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["分区", "名称", "大小", "状态", "挂载点"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.setMinimumHeight(180)
        table_layout.addWidget(self.table)
        root.addWidget(table_panel, 1)

        note = QFrame()
        note.setObjectName("warningBox")
        note_layout = QVBoxLayout(note)
        note_layout.setContentsMargins(14, 10, 14, 10)
        note_text = QLabel(
            "EFI 通常包含 OpenCore 引导文件。挂载不会修改文件，"
            "但编辑或删除 EFI 内容可能导致无法启动。"
        )
        note_text.setWordWrap(True)
        note_layout.addWidget(note_text)
        root.addWidget(note)

        action_row = QHBoxLayout()
        self.selected_label = QLabel("未选择 EFI 分区")
        self.selected_label.setObjectName("muted")
        action_row.addWidget(self.selected_label)
        action_row.addStretch(1)
        self.open_button = action_button("在 Finder 中打开", "folder-open")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_mount_point)
        action_row.addWidget(self.open_button)
        self.unmount_button = action_button("卸载 EFI", "hard-drive")
        self.unmount_button.setEnabled(False)
        self.unmount_button.clicked.connect(self.unmount_selected)
        action_row.addWidget(self.unmount_button)
        self.mount_button = action_button(
            "挂载 EFI",
            "hard-drive",
            role="primary",
        )
        self.mount_button.setEnabled(False)
        self.mount_button.clicked.connect(self.mount_selected)
        action_row.addWidget(self.mount_button)
        root.addLayout(action_row)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        try:
            self.partitions = self.manager.list_partitions()
        except Exception as exc:
            show_error(self, "无法读取 EFI 分区", exc)
            return
        self.table.setRowCount(len(self.partitions))
        for row, partition in enumerate(self.partitions):
            self.table.setItem(row, 0, QTableWidgetItem(partition.identifier))
            self.table.setItem(row, 1, QTableWidgetItem(partition.volume_name))
            self.table.setItem(
                row,
                2,
                QTableWidgetItem(_human_size(partition.size_bytes)),
            )
            status_cell = QWidget()
            status_layout = QHBoxLayout(status_cell)
            status_layout.setContentsMargins(5, 3, 5, 3)
            status_layout.addWidget(
                status_badge(
                    "已挂载" if partition.mounted else "未挂载",
                    "allowed" if partition.mounted else "none",
                )
            )
            status_layout.addStretch(1)
            self.table.setCellWidget(row, 3, status_cell)
            self.table.setItem(
                row,
                4,
                QTableWidgetItem(
                    str(partition.mount_point)
                    if partition.mount_point is not None
                    else "—"
                ),
            )
            self.table.setRowHeight(row, 39)
        self.status_label.setText(
            f"{len(self.partitions)} 个 EFI 分区"
            if self.partitions
            else "未发现 EFI 分区"
        )
        self._selection_changed()

    def selected_partition(self) -> EFIPartition | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self.partitions):
            return self.partitions[row]
        return None

    def _selection_changed(self) -> None:
        partition = self.selected_partition()
        if partition is None:
            self.selected_label.setText("未选择 EFI 分区")
            self.mount_button.setEnabled(False)
            self.unmount_button.setEnabled(False)
            self.open_button.setEnabled(False)
            return
        self.selected_label.setText(f"{partition.identifier} · {partition.volume_name}")
        self.mount_button.setEnabled(not partition.mounted)
        self.unmount_button.setEnabled(partition.mounted)
        self.open_button.setEnabled(partition.mounted)

    def mount_selected(self) -> None:
        partition = self.selected_partition()
        if partition is None or partition.mounted:
            return
        answer = QMessageBox.warning(
            self,
            "挂载 EFI 分区",
            f"即将挂载 {partition.identifier}。\n\n"
            "EFI 可能包含 OpenCore 引导文件，请勿在未备份时修改内容。"
            "继续后系统会请求管理员授权。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            mounted = self.manager.mount(
                partition.identifier,
                confirmed=True,
            )
        except Exception as exc:
            show_error(self, "挂载 EFI 失败", exc)
            self.refresh()
            return
        self.audit.event(
            "mount_efi",
            identifier=mounted.identifier,
            mount_point=mounted.mount_point,
        )
        self.refresh()
        QMessageBox.information(
            self,
            "EFI 已挂载",
            f"挂载点：{mounted.mount_point}",
        )

    def unmount_selected(self) -> None:
        partition = self.selected_partition()
        if partition is None or not partition.mounted:
            return
        answer = QMessageBox.question(
            self,
            "卸载 EFI 分区",
            f"确定卸载 {partition.identifier} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            unmounted = self.manager.unmount(
                partition.identifier,
                confirmed=True,
            )
        except Exception as exc:
            show_error(self, "卸载 EFI 失败", exc)
            self.refresh()
            return
        self.audit.event("unmount_efi", identifier=unmounted.identifier)
        self.refresh()

    def open_mount_point(self) -> None:
        partition = self.selected_partition()
        if partition is None or partition.mount_point is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(partition.mount_point)))


def _human_size(value: int) -> str:
    if value <= 0:
        return "未知"
    if value >= 1024**3:
        return f"{value / 1024**3:.1f} GB"
    if value >= 1024**2:
        return f"{value / 1024**2:.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value} B"
