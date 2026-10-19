"""Immediate app-first permission toggles for the user-level TCC database."""

from __future__ import annotations

from PyQt6.QtCore import QFileInfo, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QFileIconProvider,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tcc_permission_assistant.core.app_names import chinese_app_names
from tcc_permission_assistant.core.backup import BackupManager
from tcc_permission_assistant.core.injector import (
    build_injection_plan,
    execute_dynamic_injection,
)
from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.core.models import (
    AppScanResult,
    PermissionAction,
    PermissionStatus,
    TCCDatabaseScope,
    TCCService,
)
from tcc_permission_assistant.core.permission_map import (
    get_service_definition,
    supported_services,
)
from tcc_permission_assistant.core.settings import LANGUAGE_ZH_HANS
from tcc_permission_assistant.core.tcc_db import TCCDatabase
from tcc_permission_assistant.gui.app_inventory import AppInventoryWorker
from tcc_permission_assistant.gui.components import (
    TaskThread,
    ToggleSwitch,
    action_button,
    page_header,
    panel,
    section_title,
    status_badge,
)
from tcc_permission_assistant.gui.tcc_state import (
    STATUS_BADGE_STATES,
    STATUS_LABELS,
    permission_statuses,
)
from tcc_permission_assistant.gui.theme import COLORS


class DynamicPermissionsPage(QWidget):
    """Manage related permissions for one application with immediate switches."""

    environment_changed = pyqtSignal()

    def __init__(
        self,
        audit: AuditLogger,
        parent: QWidget | None = None,
        *,
        database: TCCDatabase | None = None,
        backup_manager: BackupManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.audit = audit
        self.database = database or TCCDatabase.for_scope(TCCDatabaseScope.USER)
        self.backup_manager = backup_manager or BackupManager()
        self.inventory: tuple[AppScanResult, ...] = ()
        self.current_result: AppScanResult | None = None
        self.current_statuses: dict[TCCService, PermissionStatus] = {}
        self._result_by_bundle_id: dict[str, AppScanResult] = {}
        self._display_name_by_bundle_id: dict[str, str] = {}
        self._service_by_row: dict[int, TCCService] = {}
        self._switch_by_service: dict[TCCService, ToggleSwitch] = {}
        self._inventory_worker: AppInventoryWorker | None = None
        self._inventory_loaded = False
        self._updating = False
        self._writing = False
        self._status_error: str | None = None
        self._write_worker: TaskThread | None = None
        self._pending_toggle: tuple[TCCService, bool, AppScanResult] | None = None
        self._icon_provider = QFileIconProvider()
        self._icon_by_bundle_id: dict[str, QIcon] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(13)

        self.refresh_button = action_button("刷新应用", "refresh-cw")
        self.refresh_button.clicked.connect(self.refresh_inventory)
        header, _ = page_header(
            "动态权限",
            "用户级 TCC.db · 开关即时生效 · 自动备份",
            [self.refresh_button],
        )
        root.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)

        apps_panel, apps_layout = panel()
        apps_panel.setMinimumWidth(250)
        apps_header = QHBoxLayout()
        apps_header.addWidget(section_title("应用"))
        apps_header.addStretch(1)
        self.app_count = QLabel("0 个")
        self.app_count.setObjectName("muted")
        apps_header.addWidget(self.app_count)
        apps_layout.addLayout(apps_header)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索应用或 Bundle ID")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._filter_apps)
        apps_layout.addWidget(self.search_input)

        self.app_list = QListWidget()
        self.app_list.setObjectName("appList")
        self.app_list.setAlternatingRowColors(False)
        self.app_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.app_list.currentItemChanged.connect(self._app_selected)
        apps_layout.addWidget(self.app_list, 1)

        self.inventory_status = QLabel("正在准备应用清单")
        self.inventory_status.setObjectName("muted")
        self.inventory_status.setWordWrap(True)
        apps_layout.addWidget(self.inventory_status)
        splitter.addWidget(apps_panel)

        permissions_panel, permissions_layout = panel()
        permissions_panel.setMinimumWidth(420)
        app_header = QHBoxLayout()
        app_text = QVBoxLayout()
        app_text.setSpacing(2)
        self.app_name = QLabel("选择左侧应用")
        self.app_name.setObjectName("sectionTitle")
        self.app_identity = QLabel("—")
        self.app_identity.setObjectName("muted")
        self.app_identity.setWordWrap(True)
        self.app_identity.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        app_text.addWidget(self.app_name)
        app_text.addWidget(self.app_identity)
        app_header.addLayout(app_text, 1)
        permissions_layout.addLayout(app_header)

        permission_header = QHBoxLayout()
        permission_header.addWidget(section_title("相关权限"))
        permission_header.addStretch(1)
        self.permission_count = QLabel("0 项")
        self.permission_count.setObjectName("muted")
        permission_header.addWidget(self.permission_count)
        permissions_layout.addLayout(permission_header)

        self.permissions_table = QTableWidget(0, 4)
        self.table = self.permissions_table
        self.permissions_table.setHorizontalHeaderLabels(
            ["权限", "来源", "当前状态", "开关"]
        )
        self.permissions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.permissions_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.permissions_table.setAlternatingRowColors(True)
        self.permissions_table.verticalHeader().setVisible(False)
        table_header = self.permissions_table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.permissions_table.setColumnWidth(3, 76)
        self.permissions_table.setMinimumHeight(260)
        permissions_layout.addWidget(self.permissions_table, 1)

        self.permission_empty = QLabel("选择左侧应用后显示相关权限")
        self.permission_empty.setObjectName("muted")
        self.permission_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.permission_empty.setMinimumHeight(220)
        permissions_layout.addWidget(self.permission_empty, 1)
        self.permissions_table.setVisible(False)

        footer = QHBoxLayout()
        footer_note = QLabel("开启写入允许，关闭删除该权限记录。")
        footer_note.setObjectName("muted")
        footer_note.setWordWrap(False)
        footer_note.setMinimumWidth(270)
        footer.addWidget(footer_note)
        footer.addStretch(1)
        self.operation_status = QLabel("")
        self.operation_status.setObjectName("muted")
        self.operation_status.setWordWrap(True)
        self.operation_status.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        footer.addWidget(self.operation_status, 1)
        permissions_layout.addLayout(footer)
        splitter.addWidget(permissions_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([285, 650])
        root.addWidget(splitter, 1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._inventory_loaded and self._inventory_worker is None:
            self.refresh_inventory()

    def set_preloaded_inventory(
        self,
        results: tuple[AppScanResult, ...],
        errors: tuple[tuple[object, str], ...] = (),
    ) -> None:
        self._set_inventory(results, errors)

    def set_scan_result(self, result: AppScanResult) -> None:
        by_bundle_id = {item.bundle_id: item for item in self.inventory}
        by_bundle_id[result.bundle_id] = result
        self.inventory = tuple(by_bundle_id.values())
        self._prepare_inventory_metadata()
        self._inventory_loaded = True
        self.inventory_status.setText(f"已载入 {len(self.inventory)} 个应用")
        self._populate_app_list(select_bundle_id=result.bundle_id)

    def refresh_inventory(self) -> None:
        if self._inventory_worker is not None:
            return
        self.refresh_button.setEnabled(False)
        self.inventory_status.setText("正在扫描应用声明…")
        worker = AppInventoryWorker(
            self.audit,
            display_language=LANGUAGE_ZH_HANS,
            parent=self,
        )
        worker.progress.connect(self._inventory_progress)
        worker.loaded.connect(self._inventory_ready)
        worker.finished.connect(self._inventory_finished)
        self._inventory_worker = worker
        worker.start()

    def shutdown(self) -> None:
        worker = self._inventory_worker
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.wait()
        self._inventory_worker = None
        write_worker = self._write_worker
        if write_worker is not None and write_worker.isRunning():
            write_worker.wait()
        self._write_worker = None

    def _inventory_progress(self, index: int, total: int, name: str) -> None:
        self.inventory_status.setText(f"正在扫描 {index}/{total}：{name}")

    def _inventory_ready(self, payload: object) -> None:
        results, errors = payload
        self._set_inventory(results, errors)

    def _inventory_finished(self) -> None:
        self._inventory_worker = None
        self.refresh_button.setEnabled(True)

    def _set_inventory(
        self,
        results: tuple[object, ...],
        errors: tuple[tuple[object, str], ...],
    ) -> None:
        self.inventory = tuple(
            item for item in results if isinstance(item, AppScanResult)
        )
        self._prepare_inventory_metadata()
        self._inventory_loaded = True
        self.inventory_status.setText(
            f"已扫描 {len(self.inventory)} 个应用"
            + (f"，{len(errors)} 个读取失败" if errors else "")
        )
        self._populate_app_list()

    def _prepare_inventory_metadata(self) -> None:
        self._result_by_bundle_id = {
            result.bundle_id: result for result in self.inventory
        }
        self._display_name_by_bundle_id = chinese_app_names(self.inventory)
        self.inventory = tuple(
            sorted(
                self.inventory,
                key=lambda result: self._display_name(result).casefold(),
            )
        )
        self._result_by_bundle_id = {
            result.bundle_id: result for result in self.inventory
        }

    def _display_name(self, result: AppScanResult) -> str:
        return self._display_name_by_bundle_id.get(
            result.bundle_id,
            result.name,
        )

    def _populate_app_list(self, select_bundle_id: str | None = None) -> None:
        selected_bundle_id = select_bundle_id
        if selected_bundle_id is None and self.current_result is not None:
            selected_bundle_id = self.current_result.bundle_id

        self._filter_apps(
            self.search_input.text(),
            select_bundle_id=selected_bundle_id,
        )

    def _app_icon(self, result: AppScanResult) -> QIcon:
        cached = self._icon_by_bundle_id.get(result.bundle_id)
        if cached is not None:
            return cached
        icon = self._icon_provider.icon(QFileInfo(str(result.path)))
        self._icon_by_bundle_id[result.bundle_id] = icon
        return icon

    def _filter_apps(
        self,
        value: str,
        *,
        select_bundle_id: str | None = None,
    ) -> None:
        query = value.strip().casefold()
        selected_bundle_id = select_bundle_id
        if selected_bundle_id is None and self.app_list.currentItem() is not None:
            selected_bundle_id = str(
                self.app_list.currentItem().data(Qt.ItemDataRole.UserRole)
            )

        self.app_list.blockSignals(True)
        self.app_list.clear()
        selected_item: QListWidgetItem | None = None
        for result in self.inventory:
            display_name = self._display_name(result)
            matches = (
                not query
                or query in display_name.casefold()
                or query in result.name.casefold()
                or query in result.bundle_id.casefold()
            )
            if not matches:
                continue
            item = QListWidgetItem(self._app_icon(result), display_name)
            item.setData(Qt.ItemDataRole.UserRole, result.bundle_id)
            item.setToolTip(f"{result.path}\n{result.bundle_id}")
            item.setSizeHint(QSize(0, 42))
            self.app_list.addItem(item)
            if result.bundle_id == selected_bundle_id:
                selected_item = item
        self.app_list.blockSignals(False)
        visible_count = self.app_list.count()
        total = len(self.inventory)
        self.app_count.setText(
            f"{visible_count}/{total} 个" if query else f"{total} 个"
        )

        if selected_item is not None:
            self.app_list.setCurrentItem(selected_item)
        elif self.app_list.count():
            self.app_list.setCurrentRow(0)
        else:
            self.current_result = None
            self._show_empty_permissions(
                "没有匹配的应用" if query else "没有可显示的应用"
            )

    def _app_selected(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            self.current_result = None
            self._show_empty_permissions("选择左侧应用后显示相关权限")
            return
        bundle_id = str(current.data(Qt.ItemDataRole.UserRole))
        result = self._result_by_bundle_id.get(bundle_id)
        if result is None:
            self.current_result = None
            self._show_empty_permissions("无法读取所选应用")
            return
        self.current_result = result
        self.app_name.setText(self._display_name(result))
        self.app_identity.setText(f"{result.bundle_id} · {result.path}")
        self.app_identity.setToolTip(str(result.path))
        self._set_operation_status("")
        self.refresh_permissions()

    def refresh_permissions(self, *, status_message: str = "") -> None:
        result = self.current_result
        if result is None:
            self._show_empty_permissions("选择左侧应用后显示相关权限")
            return

        services = supported_services()
        status_error: str | None = None
        try:
            statuses = permission_statuses(
                result.bundle_id,
                services,
                database=self.database,
            )
        except Exception as exc:
            statuses = {service: PermissionStatus.UNKNOWN for service in services}
            status_error = str(exc)
        self._status_error = status_error
        self.current_statuses = statuses
        declared = set(result.recommended_services)
        related_services = [
            service
            for service in services
            if service in declared
            or statuses.get(service, PermissionStatus.NO_RECORD)
            is not PermissionStatus.NO_RECORD
        ]
        self.permission_count.setText(f"{len(related_services)} 项")

        if not related_services:
            self._show_empty_permissions("该应用没有声明权限，TCC 中也没有相关记录")
            if status_error:
                self._set_operation_status(
                    f"权限状态读取失败：{status_error}",
                    error=True,
                )
            elif status_message:
                self._set_operation_status(status_message)
            return

        declarations = {
            declaration.service: declaration for declaration in result.permissions
        }
        self.permissions_table.setVisible(True)
        self.permission_empty.setVisible(False)
        self.permissions_table.blockSignals(True)
        self.permissions_table.clearContents()
        self.permissions_table.setRowCount(0)
        self.permissions_table.setRowCount(len(related_services))
        self._service_by_row.clear()
        self._switch_by_service.clear()
        for row, service in enumerate(related_services):
            self._service_by_row[row] = service
            definition = get_service_definition(service)
            status = statuses.get(service, PermissionStatus.UNKNOWN)
            declaration = declarations.get(service)
            source_parts = []
            if service in declared:
                source_parts.append("应用声明")
            if status is not PermissionStatus.NO_RECORD:
                source_parts.append("已有记录")

            name_item = QTableWidgetItem(definition.display_name)
            tooltip = service.value
            if declaration is not None and declaration.description:
                tooltip += f"\n{declaration.description}"
            name_item.setToolTip(tooltip)
            self.permissions_table.setItem(row, 0, name_item)
            self.permissions_table.setItem(
                row,
                1,
                QTableWidgetItem(" · ".join(source_parts)),
            )

            status_cell = QWidget()
            status_layout = QHBoxLayout(status_cell)
            status_layout.setContentsMargins(5, 2, 5, 2)
            status_layout.addWidget(
                status_badge(
                    STATUS_LABELS[status],
                    STATUS_BADGE_STATES[status],
                )
            )
            status_layout.addStretch(1)
            self.permissions_table.setCellWidget(row, 2, status_cell)

            switch = ToggleSwitch(
                accessible_name=f"{definition.display_name}权限",
            )
            switch.setToolTip("开启并写入允许；关闭并删除权限记录")
            switch.setChecked(status is PermissionStatus.ALLOWED)
            switch.setEnabled(not self._writing and status_error is None)
            if status_error is not None:
                switch.setToolTip("权限状态不可信，重新读取成功后才能修改。")
            switch.toggled.connect(
                lambda checked, selected=service: self._toggle_permission(
                    selected,
                    checked,
                )
            )
            switch_cell = QWidget()
            switch_layout = QHBoxLayout(switch_cell)
            switch_layout.setContentsMargins(12, 2, 12, 2)
            switch_layout.addWidget(switch)
            self.permissions_table.setCellWidget(row, 3, switch_cell)
            self._switch_by_service[service] = switch
            self.permissions_table.setRowHeight(row, 48)
        self.permissions_table.blockSignals(False)

        if status_error:
            self._set_operation_status(
                f"权限状态读取失败：{status_error}",
                error=True,
            )
        elif status_message:
            self._set_operation_status(status_message)

    def _toggle_permission(self, service: TCCService, enabled: bool) -> None:
        result = self.current_result
        if self._updating or self._writing or result is None:
            return
        if self._status_error is not None:
            self._set_operation_status(
                f"权限状态读取失败：{self._status_error}",
                error=True,
            )
            return
        action = PermissionAction.ALLOW if enabled else PermissionAction.DELETE
        self._writing = True
        self._set_switches_enabled(False)
        self._set_operation_status("正在写入用户级 TCC.db…")
        self._pending_toggle = (service, enabled, result)

        def perform() -> tuple[object, object]:
            plan = build_injection_plan(
                self.database,
                result.bundle_id,
                service,
                action,
            )
            outcome = execute_dynamic_injection(
                plan,
                backup_manager=self.backup_manager,
            )
            return plan, outcome

        worker = TaskThread(perform, self)
        worker.succeeded.connect(self._toggle_succeeded)
        worker.failed.connect(self._toggle_failed)
        worker.finished.connect(self._toggle_worker_finished)
        self._write_worker = worker
        worker.start()

    def _toggle_succeeded(self, payload: object) -> None:
        pending = self._pending_toggle
        if pending is None:
            return
        service, enabled, result = pending
        definition = get_service_definition(service)
        plan, outcome = payload
        if outcome.success:
            self.audit.event(
                "gui_dynamic_permission",
                bundle_id=result.bundle_id,
                service=service.value,
                enabled=enabled,
                action=plan.action.value,
                backup_path=outcome.backup.path,
                rows_changed=outcome.rows_changed,
                verification=outcome.verification.actual_status.value,
            )
            action_text = "已开启" if enabled else "已关闭并删除记录"
            self.environment_changed.emit()
            self._finish_toggle(
                f"{definition.display_name} {action_text}",
            )
            return

        rollback_text = (
            "，已自动回滚到备份"
            if outcome.rolled_back
            else (
                f"，自动回滚失败：{outcome.rollback_error}"
                if outcome.rollback_error
                else ""
            )
        )
        error_message = (
            f"{definition.display_name} 写入后状态为 "
            f"{STATUS_LABELS[outcome.verification.actual_status]}"
            f"{rollback_text}"
        )
        self._record_toggle_error(
            service,
            enabled,
            result,
            error_message,
            rolled_back=outcome.rolled_back,
            rollback_error=outcome.rollback_error,
        )
        self._finish_toggle(error_message, error=True)

    def _toggle_failed(self, error: object) -> None:
        pending = self._pending_toggle
        if pending is None:
            return
        service, enabled, result = pending
        definition = get_service_definition(service)
        message = f"{definition.display_name} 操作失败：{error}"
        self._record_toggle_error(
            service,
            enabled,
            result,
            message,
        )
        self._finish_toggle(message, error=True)

    def _record_toggle_error(
        self,
        service: TCCService,
        enabled: bool,
        result: AppScanResult,
        message: str,
        *,
        rolled_back: bool = False,
        rollback_error: str | None = None,
    ) -> None:
        self.audit.event(
            "gui_dynamic_permission_error",
            bundle_id=result.bundle_id,
            service=service.value,
            enabled=enabled,
            error_type="InjectionError",
            error=message,
            rolled_back=rolled_back,
            rollback_error=rollback_error,
        )

    def _toggle_worker_finished(self) -> None:
        worker = self._write_worker
        if worker is not None:
            worker.deleteLater()
        self._write_worker = None

    def _finish_toggle(self, status_message: str, *, error: bool = False) -> None:
        self._writing = False
        self._pending_toggle = None
        self._updating = True
        try:
            self.refresh_permissions(status_message=status_message)
            if error:
                self._set_operation_status(status_message, error=True)
        finally:
            self._updating = False

    def _set_switches_enabled(self, enabled: bool) -> None:
        for switch in self._switch_by_service.values():
            switch.setEnabled(enabled)

    def _show_empty_permissions(self, message: str) -> None:
        self.permissions_table.setVisible(False)
        self.permission_empty.setText(message)
        self.permission_empty.setVisible(True)
        self.permission_count.setText("0 项")
        self.current_statuses = {}
        self._status_error = None
        self._service_by_row.clear()
        self._switch_by_service.clear()

    def _set_operation_status(self, message: str, *, error: bool = False) -> None:
        self.operation_status.setText(message)
        self.operation_status.setStyleSheet(
            f"color: {COLORS['danger'] if error else COLORS['muted']};"
        )
