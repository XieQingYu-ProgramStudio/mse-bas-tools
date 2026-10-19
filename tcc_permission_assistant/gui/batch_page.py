"""Permission-first batch authorization wizard."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
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

from tcc_permission_assistant.core.backup import BackupManager
from tcc_permission_assistant.core.injector import (
    CONFIRMATION_PHRASE,
    InjectionConfirmation,
    build_injection_plan,
    execute_batch_injection,
)
from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.core.models import (
    AppScanResult,
    InjectionPlan,
    PermissionAction,
    PermissionStatus,
    TCCDatabaseScope,
    TCCService,
)
from tcc_permission_assistant.core.permission_map import (
    get_service_definition,
    supported_services,
)
from tcc_permission_assistant.core.settings import LANGUAGE_SYSTEM
from tcc_permission_assistant.core.tcc_db import TCCDatabase
from tcc_permission_assistant.gui.app_inventory import AppInventoryWorker
from tcc_permission_assistant.gui.components import (
    DangerousConfirmationDialog,
    action_button,
    page_header,
    panel,
    section_title,
    show_error,
    status_badge,
)
from tcc_permission_assistant.gui.tcc_state import (
    STATUS_LABELS,
    permission_statuses,
)


@dataclass(frozen=True, slots=True)
class BatchCandidate:
    result: AppScanResult
    matched_services: tuple[TCCService, ...]
    statuses: dict[TCCService, PermissionStatus]


class BatchPage(QWidget):
    def __init__(
        self,
        audit: AuditLogger,
        parent: QWidget | None = None,
        *,
        app_name_language: str = LANGUAGE_SYSTEM,
    ) -> None:
        super().__init__(parent)
        self.audit = audit
        self.app_name_language = app_name_language
        self.inventory: tuple[AppScanResult, ...] = ()
        self.candidates: tuple[BatchCandidate, ...] = ()
        self._candidate_by_row: dict[int, BatchCandidate] = {}
        self._permission_checks: dict[TCCService, QCheckBox] = {}
        self._inventory_worker: AppInventoryWorker | None = None
        self._inventory_loaded = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(13)

        self.refresh_button = action_button("刷新应用", "refresh-cw")
        self.refresh_button.clicked.connect(self.refresh_inventory)
        header, _ = page_header(
            "批量授权",
            "用户级 TCC.db · 默认 dry-run",
            [self.refresh_button],
        )
        root.addWidget(header)

        permission_panel, permission_layout = panel()
        permission_header = QHBoxLayout()
        permission_header.addWidget(self._step_title("1", "选择权限"))
        permission_header.addStretch(1)
        self.permission_count = QLabel("未选择")
        self.permission_count.setObjectName("muted")
        permission_header.addWidget(self.permission_count)
        permission_layout.addLayout(permission_header)

        service_grid = QGridLayout()
        service_grid.setHorizontalSpacing(20)
        service_grid.setVerticalSpacing(9)
        for index, service in enumerate(supported_services()):
            definition = get_service_definition(service)
            checkbox = QCheckBox(definition.display_name)
            checkbox.toggled.connect(self._permission_selection_changed)
            self._permission_checks[service] = checkbox
            service_grid.addWidget(checkbox, index // 4, index % 4)
        permission_layout.addLayout(service_grid)
        root.addWidget(permission_panel)

        apps_panel, apps_layout = panel()
        apps_header = QHBoxLayout()
        apps_header.addWidget(self._step_title("2", "选择应用"))
        apps_header.addSpacing(8)
        self.candidate_count = QLabel("先选择权限")
        self.candidate_count.setObjectName("muted")
        apps_header.addWidget(self.candidate_count)
        apps_header.addStretch(1)
        self.select_all_button = action_button("全选显示项")
        self.select_all_button.setEnabled(False)
        self.select_all_button.clicked.connect(self.select_all_candidates)
        self.clear_button = action_button("清除选择")
        self.clear_button.setEnabled(False)
        self.clear_button.clicked.connect(self.clear_selection)
        apps_header.addWidget(self.select_all_button)
        apps_header.addWidget(self.clear_button)
        apps_layout.addLayout(apps_header)

        self.apps_table = QTableWidget(0, 5)
        self.apps_table.setHorizontalHeaderLabels(
            ["选择", "应用", "Bundle ID", "匹配权限", "当前状态"]
        )
        self.apps_table.setAlternatingRowColors(True)
        self.apps_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.apps_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.apps_table.verticalHeader().setVisible(False)
        table_header = self.apps_table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.apps_table.itemChanged.connect(self._app_selection_changed)
        self.apps_table.setMinimumHeight(118)
        apps_layout.addWidget(self.apps_table)
        self.inventory_status = QLabel("正在准备应用清单")
        self.inventory_status.setObjectName("muted")
        self.inventory_status.setMinimumHeight(16)
        apps_layout.addWidget(self.inventory_status)
        root.addWidget(apps_panel, 1)

        plan_panel, plan_layout = panel()
        plan_header = QHBoxLayout()
        plan_header.addWidget(self._step_title("3", "批量计划"))
        plan_header.addStretch(1)
        self.selection_count = QLabel("未选择应用")
        self.selection_count.setObjectName("muted")
        plan_header.addWidget(self.selection_count)
        plan_layout.addLayout(plan_header)

        action_row = QHBoxLayout()
        self.dry_run_checkbox = QCheckBox("仅生成 SQL（dry-run）")
        self.dry_run_checkbox.setChecked(True)
        self.dry_run_checkbox.toggled.connect(self._mode_changed)
        action_row.addWidget(self.dry_run_checkbox)
        action_row.addStretch(1)
        self.run_button = action_button(
            "生成批量计划",
            "file-down",
            role="primary",
        )
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.run_batch)
        action_row.addWidget(self.run_button)
        plan_layout.addLayout(action_row)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("选择应用后生成批量 SQL。")
        self.preview.setMinimumHeight(88)
        plan_layout.addWidget(self.preview)
        root.addWidget(plan_panel)

    @staticmethod
    def _step_title(number: str, title: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(status_badge(number, "accent"))
        layout.addWidget(section_title(title))
        return widget

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._inventory_loaded and self._inventory_worker is None:
            self.refresh_inventory()

    def set_preloaded_inventory(
        self,
        results: tuple[AppScanResult, ...],
        errors: tuple[tuple[object, str], ...] = (),
    ) -> None:
        """Accept startup scan results without starting a second scan."""

        self.inventory = results
        self._inventory_loaded = True
        self.inventory_status.setText(
            f"已扫描 {len(results)} 个应用"
            + (f"，{len(errors)} 个读取失败" if errors else "")
        )
        self._permission_selection_changed()

    def selected_services(self) -> tuple[TCCService, ...]:
        return tuple(
            service
            for service, checkbox in self._permission_checks.items()
            if checkbox.isChecked()
        )

    def refresh_inventory(self) -> None:
        if self._inventory_worker is not None:
            return
        self.refresh_button.setEnabled(False)
        self.inventory_status.setText("正在扫描应用声明…")
        worker = AppInventoryWorker(
            self.audit,
            display_language=self.app_name_language,
            parent=self,
        )
        worker.progress.connect(self._inventory_progress)
        worker.loaded.connect(self._inventory_ready)
        worker.finished.connect(self._inventory_finished)
        self._inventory_worker = worker
        worker.start()

    def _inventory_progress(self, index: int, total: int, name: str) -> None:
        self.inventory_status.setText(f"正在扫描 {index}/{total}：{name}")

    def _inventory_ready(self, payload: object) -> None:
        results, errors = payload
        self.inventory = results
        self._inventory_loaded = True
        self.inventory_status.setText(
            f"已扫描 {len(results)} 个应用"
            + (f"，{len(errors)} 个读取失败" if errors else "")
        )
        self._permission_selection_changed()

    def _inventory_finished(self) -> None:
        self._inventory_worker = None
        self.refresh_button.setEnabled(True)

    def shutdown(self) -> None:
        worker = self._inventory_worker
        if worker is None or not worker.isRunning():
            return
        worker.requestInterruption()
        if not worker.wait(3000):
            worker.terminate()
            worker.wait(1000)

    def set_app_name_language(self, language: str) -> None:
        if language == self.app_name_language:
            return
        self.app_name_language = language
        self.inventory = ()
        self.candidates = ()
        self._inventory_loaded = False
        self.apps_table.setRowCount(0)
        self.candidate_count.setText("等待重新扫描")
        self.inventory_status.setText("应用名称语言已更改")
        if self.isVisible():
            self.refresh_inventory()

    def _permission_selection_changed(self) -> None:
        selected = self.selected_services()
        self.permission_count.setText(
            f"已选择 {len(selected)} 项" if selected else "未选择"
        )
        if not selected:
            self.candidates = ()
            self.apps_table.setRowCount(0)
            self.candidate_count.setText("先选择权限")
            self.inventory_status.setText("选择权限后显示声明过这些权限的应用")
            self._app_selection_changed()
            return
        if not self._inventory_loaded:
            self.candidate_count.setText("正在扫描应用")
            return
        self._build_candidates(selected)

    def _build_candidates(self, selected: tuple[TCCService, ...]) -> None:
        checked_paths = {
            candidate.result.path
            for row, candidate in self._candidate_by_row.items()
            if (
                (item := self.apps_table.item(row, 0)) is not None
                and item.checkState() == Qt.CheckState.Checked
            )
        }
        database = TCCDatabase.for_scope(TCCDatabaseScope.USER)
        candidates: list[BatchCandidate] = []
        for result in self.inventory:
            matched = tuple(
                service
                for service in selected
                if service in result.recommended_services
            )
            if not matched:
                continue
            try:
                statuses = permission_statuses(
                    result.bundle_id,
                    matched,
                    database=database,
                )
            except Exception:
                statuses = {service: PermissionStatus.UNKNOWN for service in matched}
            candidates.append(
                BatchCandidate(
                    result=result,
                    matched_services=matched,
                    statuses=statuses,
                )
            )
        self.candidates = tuple(candidates)
        self._candidate_by_row.clear()
        self.apps_table.blockSignals(True)
        self.apps_table.setRowCount(len(self.candidates))
        for row, candidate in enumerate(self.candidates):
            self._candidate_by_row[row] = candidate
            item = QTableWidgetItem()
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(
                Qt.CheckState.Checked
                if candidate.result.path in checked_paths
                else Qt.CheckState.Unchecked
            )
            self.apps_table.setItem(row, 0, item)
            name_item = QTableWidgetItem(candidate.result.name)
            name_item.setToolTip(str(candidate.result.path))
            self.apps_table.setItem(row, 1, name_item)
            self.apps_table.setItem(
                row,
                2,
                QTableWidgetItem(candidate.result.bundle_id),
            )
            matched_names = "、".join(
                get_service_definition(service).display_name
                for service in candidate.matched_services
            )
            self.apps_table.setItem(row, 3, QTableWidgetItem(matched_names))
            status_text = "；".join(
                f"{get_service_definition(service).display_name} "
                f"{STATUS_LABELS[candidate.statuses[service]]}"
                for service in candidate.matched_services
            )
            self.apps_table.setItem(row, 4, QTableWidgetItem(status_text))
            self.apps_table.setRowHeight(row, 39)
        self.apps_table.blockSignals(False)
        self.candidate_count.setText(f"{len(self.candidates)} 个候选应用")
        self.inventory_status.setText(
            "仅列出声明过所选权限的应用" if self.candidates else "没有应用声明所选权限"
        )
        self._app_selection_changed()

    def _app_selection_changed(self, _item=None) -> None:
        selected = self.selected_candidates()
        plan_count = sum(len(candidate.matched_services) for candidate in selected)
        self.selection_count.setText(
            f"{len(selected)} 个应用 / {plan_count} 项授权"
            if selected
            else "未选择应用"
        )
        has_candidates = bool(self.candidates)
        self.select_all_button.setEnabled(has_candidates)
        self.clear_button.setEnabled(bool(selected))
        self.run_button.setEnabled(bool(selected))

    def selected_candidates(self) -> tuple[BatchCandidate, ...]:
        return tuple(
            candidate
            for row, candidate in self._candidate_by_row.items()
            if (
                (item := self.apps_table.item(row, 0)) is not None
                and item.checkState() == Qt.CheckState.Checked
            )
        )

    def select_all_candidates(self) -> None:
        self.apps_table.blockSignals(True)
        for row in range(self.apps_table.rowCount()):
            item = self.apps_table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked)
        self.apps_table.blockSignals(False)
        self._app_selection_changed()

    def clear_selection(self) -> None:
        self.apps_table.blockSignals(True)
        for row in range(self.apps_table.rowCount()):
            item = self.apps_table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Unchecked)
        self.apps_table.blockSignals(False)
        self._app_selection_changed()

    def _mode_changed(self, dry_run: bool) -> None:
        self.run_button.setText("生成批量计划" if dry_run else "执行批量授权")
        self.run_button.setObjectName("primary" if dry_run else "danger")
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)

    def _collect_plans(self) -> tuple[InjectionPlan, ...]:
        selected = self.selected_candidates()
        if not selected:
            raise ValueError("请至少选择一个应用。")
        database = TCCDatabase.for_scope(TCCDatabaseScope.USER)
        plans: list[InjectionPlan] = []
        for candidate in selected:
            for service in candidate.matched_services:
                plans.append(
                    build_injection_plan(
                        database,
                        candidate.result.bundle_id,
                        service,
                        PermissionAction.ALLOW,
                    )
                )
        return tuple(plans)

    def run_batch(self) -> None:
        try:
            plans = self._collect_plans()
        except Exception as exc:
            show_error(self, "无法生成批量计划", exc)
            return
        self.preview.setPlainText("\n\n".join(self._plan_text(plan) for plan in plans))
        dry_run = self.dry_run_checkbox.isChecked()
        self.audit.event(
            "gui_batch_generate",
            dry_run=dry_run,
            plan_count=len(plans),
            app_count=len(self.selected_candidates()),
            services=[plan.service.value for plan in plans],
        )
        if dry_run:
            QMessageBox.information(
                self,
                "批量计划已生成",
                f"已生成 {len(plans)} 项授权计划，数据库没有发生写入。",
            )
            return

        details = "\n\n".join(self._plan_text(plan) for plan in plans)
        dialog = DangerousConfirmationDialog(
            parent=self,
            title="确认批量授权",
            summary=(
                f"{len(self.selected_candidates())} 个应用 · "
                f"{len(plans)} 项权限 · 用户级 TCC.db"
            ),
            details=details,
            phrase=CONFIRMATION_PHRASE,
            execute_text="备份并批量授权",
            closed_text="我已确认以上应用都已完全退出",
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        confirmation = InjectionConfirmation(
            applications_closed=dialog.applications_closed,
            phrase=dialog.entered_phrase,
        )
        try:
            result = execute_batch_injection(
                plans,
                confirmation,
                backup_manager=BackupManager(),
            )
            self.audit.event(
                "gui_batch_inject",
                plan_count=len(plans),
                app_count=len(self.selected_candidates()),
                backup_path=result.backup.path,
                rows_changed=result.rows_changed,
                verification_count=result.verification_count,
                success=result.success,
            )
        except Exception as exc:
            show_error(self, "批量授权失败", exc)
            self._permission_selection_changed()
            return
        self._permission_selection_changed()
        if result.success:
            QMessageBox.information(
                self,
                "批量授权完成",
                f"{result.verification_count} 项权限均通过验证。\n\n"
                f"备份文件：\n{result.backup.path}\n\n"
                "请重新打开相关应用测试。",
            )
        else:
            QMessageBox.warning(
                self,
                "批量验证失败",
                f"部分权限未通过验证。\n\n备份文件：\n{result.backup.path}",
            )

    @staticmethod
    def _plan_text(plan: InjectionPlan) -> str:
        definition = get_service_definition(plan.service)
        operation = "更新" if plan.operation.value == "update" else "插入"
        return (
            f"{plan.bundle_id} / {definition.display_name}\n"
            f"操作：{operation}，auth_value={plan.auth_value}\n"
            f"SQL：{plan.statement}\n"
            f"参数：{list(plan.parameters)}"
        )
