"""Read-only application scanner page."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
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

from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.core.models import (
    AppScanResult,
    PermissionSource,
    PermissionStatus,
    SigningStatus,
)
from tcc_permission_assistant.core.permission_map import get_service_definition
from tcc_permission_assistant.core.scanner import AppScanner
from tcc_permission_assistant.core.settings import LANGUAGE_SYSTEM
from tcc_permission_assistant.gui.components import (
    action_button,
    page_header,
    panel,
    section_title,
    show_error,
    status_badge,
)
from tcc_permission_assistant.gui.icons import load_icon
from tcc_permission_assistant.gui.tcc_state import (
    STATUS_BADGE_STATES,
    STATUS_LABELS,
    permission_statuses,
)
from tcc_permission_assistant.gui.theme import COLORS

SIGNING_LABELS = {
    SigningStatus.SIGNED: "已签名",
    SigningStatus.ADHOC: "ad-hoc 签名",
    SigningStatus.UNSIGNED: "未签名",
    SigningStatus.INVALID: "签名异常",
    SigningStatus.UNKNOWN: "未知",
}

SOURCE_LABELS = {
    PermissionSource.INFO_PLIST_USAGE: "Info.plist",
    PermissionSource.ENTITLEMENT: "entitlements",
}


class ScanPage(QWidget):
    scan_completed = pyqtSignal(object)
    open_dynamic_permissions_requested = pyqtSignal()

    def __init__(
        self,
        audit: AuditLogger,
        parent: QWidget | None = None,
        *,
        display_language: str = LANGUAGE_SYSTEM,
    ) -> None:
        super().__init__(parent)
        self.audit = audit
        self.display_language = display_language
        self.current_result: AppScanResult | None = None
        self.current_statuses: dict = {}
        self.setAcceptDrops(True)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(16)

        choose_button = action_button(
            "选择应用",
            "folder-open",
            role="primary",
        )
        choose_button.clicked.connect(self.choose_application)
        header, _ = page_header(
            "扫描",
            "用户级 TCC.db · 只读",
            [choose_button],
        )
        root.addWidget(header)

        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        drop_layout = QHBoxLayout(self.drop_zone)
        drop_layout.setContentsMargins(18, 15, 18, 15)
        drop_layout.setSpacing(13)
        drop_icon = QLabel()
        drop_icon.setPixmap(
            load_icon("scan-search", COLORS["accent"], 30).pixmap(30, 30)
        )
        drop_icon.setFixedSize(34, 34)
        drop_layout.addWidget(drop_icon)
        drop_text = QVBoxLayout()
        drop_text.setSpacing(2)
        drop_title = QLabel("拖入 .app，或从磁盘选择应用")
        drop_title.setObjectName("value")
        drop_caption = QLabel("扫描过程只读，不会修改 TCC 数据库。")
        drop_caption.setObjectName("muted")
        drop_text.addWidget(drop_title)
        drop_text.addWidget(drop_caption)
        drop_layout.addLayout(drop_text, 1)
        small_choose = action_button("浏览", "folder-open")
        small_choose.clicked.connect(self.choose_application)
        drop_layout.addWidget(small_choose)
        root.addWidget(self.drop_zone)

        self.empty_label = QLabel("尚未选择应用")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setObjectName("muted")
        self.empty_label.setMinimumHeight(180)
        root.addWidget(self.empty_label, 1)

        self.result_container = QWidget()
        result_layout = QVBoxLayout(self.result_container)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(13)

        summary_panel, summary_layout = panel()
        summary_layout.addWidget(section_title("应用信息"))
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(22)
        info_grid.setVerticalSpacing(8)
        self.app_name_value = self._grid_value(info_grid, 0, 0, "应用")
        self.bundle_value = self._grid_value(info_grid, 0, 1, "Bundle ID")
        self.signing_value = self._grid_value(info_grid, 1, 0, "代码签名")
        self.team_value = self._grid_value(info_grid, 1, 1, "Team ID")
        self.version_value = self._grid_value(info_grid, 2, 0, "版本")
        self.path_value = self._grid_value(info_grid, 2, 1, "路径")
        self.bundle_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.path_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        summary_layout.addLayout(info_grid)
        result_layout.addWidget(summary_panel)

        permissions_panel, permissions_layout = panel()
        permission_header = QHBoxLayout()
        permission_header.addWidget(section_title("权限声明"))
        permission_header.addStretch(1)
        self.permission_count = QLabel("0 项")
        self.permission_count.setObjectName("muted")
        permission_header.addWidget(self.permission_count)
        permissions_layout.addLayout(permission_header)
        self.permissions_table = QTableWidget(0, 5)
        self.permissions_table.setHorizontalHeaderLabels(
            ["权限", "TCC service", "来源", "当前状态", "用途说明"]
        )
        self.permissions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.permissions_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.permissions_table.setAlternatingRowColors(True)
        self.permissions_table.verticalHeader().setVisible(False)
        header_view = self.permissions_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.permissions_table.setMinimumHeight(180)
        permissions_layout.addWidget(self.permissions_table)
        result_layout.addWidget(permissions_panel, 1)

        self.warning_panel = QFrame()
        self.warning_panel.setObjectName("warningBox")
        warning_layout = QVBoxLayout(self.warning_panel)
        warning_layout.setContentsMargins(14, 11, 14, 11)
        warning_layout.setSpacing(6)
        warning_title = QHBoxLayout()
        warning_icon = QLabel()
        warning_icon.setPixmap(
            load_icon("alert-triangle", COLORS["warning"], 16).pixmap(16, 16)
        )
        warning_title.addWidget(warning_icon)
        warning_label = QLabel("风险提示")
        warning_label.setStyleSheet(f"color: {COLORS['warning']}; font-weight: 700;")
        warning_title.addWidget(warning_label)
        warning_title.addStretch(1)
        warning_layout.addLayout(warning_title)
        self.warning_text = QPlainTextEdit()
        self.warning_text.setReadOnly(True)
        self.warning_text.setFrameShape(QFrame.Shape.NoFrame)
        self.warning_text.setMaximumHeight(104)
        self.warning_text.setStyleSheet(
            "background: transparent; border: none; padding: 0;"
        )
        warning_layout.addWidget(self.warning_text)
        result_layout.addWidget(self.warning_panel)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.dynamic_permissions_button = action_button(
            "打开动态权限",
            "plug-zap",
            role="primary",
        )
        self.dynamic_permissions_button.setEnabled(False)
        self.dynamic_permissions_button.clicked.connect(
            self.open_dynamic_permissions_requested.emit
        )
        action_row.addWidget(self.dynamic_permissions_button)
        result_layout.addLayout(action_row)

        self.result_container.setVisible(False)
        root.addWidget(self.result_container, 1)

    @staticmethod
    def _grid_value(
        layout: QGridLayout,
        row: int,
        column: int,
        title: str,
    ) -> QLabel:
        wrapper = QWidget()
        box = QVBoxLayout(wrapper)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("muted")
        value_label = QLabel("—")
        value_label.setObjectName("value")
        value_label.setWordWrap(True)
        box.addWidget(title_label)
        box.addWidget(value_label)
        layout.addWidget(wrapper, row, column)
        return value_label

    def choose_application(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 macOS 应用",
            "/Applications",
            "macOS 应用 (*.app)",
        )
        if path:
            self.scan_application(path)

    def scan_application(self, app_path: str | Path) -> None:
        bundle_path = _nearest_app_bundle(app_path)
        if bundle_path is None:
            show_error(
                self,
                "无法扫描",
                f"所选路径不在 .app 应用包内：{app_path}",
            )
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = AppScanner(
                audit_logger=self.audit,
                display_language=self.display_language,
            ).scan(bundle_path)
            try:
                statuses = permission_statuses(
                    result.bundle_id,
                    result.recommended_services,
                )
            except Exception as exc:
                statuses = {
                    service: PermissionStatus.UNKNOWN
                    for service in result.recommended_services
                }
                result = AppScanResult(
                    name=result.name,
                    path=result.path,
                    bundle_id=result.bundle_id,
                    short_version=result.short_version,
                    bundle_version=result.bundle_version,
                    signing=result.signing,
                    permissions=result.permissions,
                    recommended_services=result.recommended_services,
                    warnings=(
                        *result.warnings,
                        f"无法读取用户级 TCC 状态：{exc}",
                    ),
                )
            self.set_scan_result(result, statuses)
            self.audit.event(
                "gui_scan",
                path=result.path,
                bundle_id=result.bundle_id,
                services=[service.value for service in result.recommended_services],
                warning_count=len(result.warnings),
            )
        except Exception as exc:
            self.audit.event(
                "scan_error",
                path=bundle_path,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            show_error(self, "扫描失败", exc)
        finally:
            QApplication.restoreOverrideCursor()

    def set_scan_result(
        self,
        result: AppScanResult,
        statuses: dict,
    ) -> None:
        self.current_result = result
        self.current_statuses = statuses
        self.empty_label.setVisible(False)
        self.result_container.setVisible(True)
        self.drop_zone.setVisible(False)

        self.app_name_value.setText(result.name)
        self.bundle_value.setText(result.bundle_id)
        signing = SIGNING_LABELS[result.signing.status]
        if result.signing.team_id:
            signing += f" · {result.signing.team_id}"
        self.signing_value.setText(signing)
        self.team_value.setText(result.signing.team_id or "未发现")
        versions = [
            value for value in (result.short_version, result.bundle_version) if value
        ]
        self.version_value.setText(" / ".join(versions) or "未知")
        self.path_value.setText(str(result.path))
        self.permission_count.setText(f"{len(result.permissions)} 项")

        self.permissions_table.setRowCount(len(result.permissions))
        for row, declaration in enumerate(result.permissions):
            definition = get_service_definition(declaration.service)
            self.permissions_table.setItem(
                row,
                0,
                QTableWidgetItem(definition.display_name),
            )
            self.permissions_table.setItem(
                row,
                1,
                QTableWidgetItem(declaration.service.value),
            )
            self.permissions_table.setItem(
                row,
                2,
                QTableWidgetItem(SOURCE_LABELS[declaration.source]),
            )
            status = statuses.get(
                declaration.service,
                PermissionStatus.UNKNOWN,
            )
            badge = status_badge(
                STATUS_LABELS[status],
                STATUS_BADGE_STATES[status],
            )
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(6, 3, 6, 3)
            cell_layout.addWidget(badge)
            cell_layout.addStretch(1)
            self.permissions_table.setCellWidget(row, 3, cell)
            description = declaration.description or "—"
            self.permissions_table.setItem(
                row,
                4,
                QTableWidgetItem(description),
            )
            self.permissions_table.setRowHeight(row, 38)

        self.warning_text.setPlainText(
            "\n".join(f"• {warning}" for warning in result.warnings)
        )
        self.dynamic_permissions_button.setEnabled(bool(result.recommended_services))
        self.scan_completed.emit(result)

    def set_app_name_language(self, language: str) -> None:
        if language == self.display_language:
            return
        self.display_language = language
        if self.current_result is not None:
            self.scan_application(self.current_result.path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.casefold().endswith(".app"):
                self.scan_application(path)
                event.acceptProposedAction()
                return
        QMessageBox.information(self, "无法扫描", "请拖入 .app 应用包。")


def _nearest_app_bundle(path: str | Path) -> Path | None:
    candidate = Path(path).expanduser().absolute()
    for item in (candidate, *candidate.parents):
        if item.suffix.casefold() == ".app" and item.is_dir():
            return item
    return None
