"""SIP, AMFI, and TCC database diagnostics page."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from tcc_permission_assistant.core.diagnostics import (
    BootArgsState,
    DiagnosticReport,
    DiagnosticsCollector,
    SIPState,
    write_diagnostic_report,
)
from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.gui.components import (
    action_button,
    page_header,
    panel,
    section_title,
    show_error,
)


class DiagnosticsPage(QWidget):
    environment_updated = pyqtSignal(object)

    def __init__(self, audit: AuditLogger, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.audit = audit
        self.report: DiagnosticReport | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(14)

        self.run_button = action_button(
            "重新诊断",
            "refresh-cw",
            role="primary",
        )
        self.run_button.clicked.connect(self.collect)
        header, _ = page_header(
            "诊断",
            "只读环境检查",
            [self.run_button],
        )
        root.addWidget(header)

        summary_panel, summary_layout = panel()
        title_row = QHBoxLayout()
        title_row.addWidget(section_title("环境概览"))
        title_row.addStretch(1)
        self.advanced_checkbox = QCheckBox("只读检查系统级 schema")
        title_row.addWidget(self.advanced_checkbox)
        summary_layout.addLayout(title_row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(12)
        self.sip_value = self._summary_item(grid, 0, 0, "SIP")
        self.boot_value = self._summary_item(grid, 0, 1, "boot-args")
        self.amfi_value = self._summary_item(grid, 0, 2, "AMFIPass / AMFI")
        self.user_db_value = self._summary_item(grid, 1, 0, "用户级 TCC.db")
        self.system_db_value = self._summary_item(grid, 1, 1, "系统级 TCC.db")
        self.fda_value = self._summary_item(grid, 1, 2, "完全磁盘访问")
        summary_layout.addLayout(grid)
        root.addWidget(summary_panel)

        report_panel, report_layout = panel()
        report_header = QHBoxLayout()
        report_header.addWidget(section_title("诊断报告"))
        report_header.addStretch(1)
        export_md = action_button("导出 Markdown", "file-down")
        export_md.clicked.connect(lambda: self.export_report("markdown"))
        export_json = action_button("导出 JSON", "file-down")
        export_json.clicked.connect(lambda: self.export_report("json"))
        report_header.addWidget(export_md)
        report_header.addWidget(export_json)
        report_layout.addLayout(report_header)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setPlaceholderText("运行诊断后在此查看完整报告。")
        report_layout.addWidget(self.browser, 1)
        root.addWidget(report_panel, 1)

    @staticmethod
    def _summary_item(
        layout: QGridLayout,
        row: int,
        column: int,
        title: str,
    ) -> QLabel:
        wrapper = QWidget()
        box = QVBoxLayout(wrapper)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        label = QLabel(title)
        label.setObjectName("muted")
        value = QLabel("—")
        value.setObjectName("value")
        value.setWordWrap(True)
        box.addWidget(label)
        box.addWidget(value)
        layout.addWidget(wrapper, row, column)
        return value

    def collect(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.report = DiagnosticsCollector().collect(
                advanced=self.advanced_checkbox.isChecked()
            )
        except Exception as exc:
            show_error(self, "诊断失败", exc)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._update_report()
        self.audit.event(
            "gui_diagnose",
            advanced=self.report.advanced,
            sip=self.report.sip.state.value,
            detected_flags=list(self.report.boot_args.detected_flags),
            user_db_readable=self.report.user_database.schema_readable,
            warning_count=len(self.report.warnings),
        )
        for command in self.report.commands:
            self.audit.event(
                "command",
                label=command.label,
                command=list(command.command),
                returncode=command.returncode,
                completed=command.completed,
            )
        self.environment_updated.emit(self.report)

    def _update_report(self) -> None:
        if self.report is None:
            return
        report = self.report
        sip_labels = {
            SIPState.ENABLED: "已启用",
            SIPState.DISABLED: "已关闭",
            SIPState.UNKNOWN: "自定义 / 未知",
            SIPState.ERROR: "读取失败",
        }
        self.sip_value.setText(sip_labels[report.sip.state])
        boot_labels = {
            BootArgsState.PRESENT: (
                f"{len(report.boot_args.detected_flags)} 个关键标志"
                if report.boot_args.detected_flags
                else "已设置，无关键标志"
            ),
            BootArgsState.NOT_SET: "未设置",
            BootArgsState.ERROR: "读取失败",
        }
        self.boot_value.setText(boot_labels[report.boot_args.state])
        self.boot_value.setToolTip(
            ", ".join(report.boot_args.detected_flags) or report.boot_args.raw_value
        )
        self.amfi_value.setText(
            "检测到冲突风险"
            if report.amfipass_detected
            and "amfi=0x80" in report.boot_args.detected_flags
            else ("检测到 AMFIPass" if report.amfipass_detected else "未见冲突标志")
        )
        self.user_db_value.setText(
            (
                f"可读 · {report.user_database.access_row_count} 条记录"
                if report.user_database.schema_readable
                else "不可读"
            )
            if report.user_database.exists
            else "文件不存在"
        )
        self.system_db_value.setText(
            "可读"
            if report.system_database.schema_readable
            else ("存在 · schema 未检查" if report.system_database.exists else "不存在")
        )
        self.fda_value.setText(
            "可能缺失" if report.likely_missing_full_disk_access else "未见明显缺失"
        )
        self.browser.setMarkdown(report.to_markdown())

    def export_report(self, report_format: str) -> None:
        if self.report is None:
            QMessageBox.information(self, "尚未诊断", "请先运行一次诊断。")
            return
        suffix = "json" if report_format == "json" else "md"
        default_name = (
            f"TCC-diagnostic-{datetime.now().strftime('%Y%m%d-%H%M%S')}.{suffix}"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出诊断报告",
            str(Path.home() / "Desktop" / default_name),
            "JSON (*.json)" if suffix == "json" else "Markdown (*.md)",
        )
        if not path:
            return
        try:
            output_path = write_diagnostic_report(
                self.report,
                path,
                report_format=report_format,
            )
        except Exception as exc:
            show_error(self, "导出失败", exc)
            return
        self.audit.event(
            "export_diagnostic",
            format=report_format,
            output=output_path,
        )
        QMessageBox.information(
            self,
            "报告已导出",
            f"已写入：\n{output_path}",
        )
