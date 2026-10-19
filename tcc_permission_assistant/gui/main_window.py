"""Main window and toolbox navigation shell."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tcc_permission_assistant import __version__
from tcc_permission_assistant.branding import (
    APP_CAPTION,
    APP_NAME,
    APP_SHORT_NAME,
    DEVELOPER_NAME,
    EFI_PAGE_NAME,
    PERMISSION_MODULE_DESCRIPTION,
    PERMISSION_MODULE_NAME,
    SYSTEM_MODULE_NAME,
    UPDATE_BADGE_PAGE_NAME,
)
from tcc_permission_assistant.core.diagnostics import (
    DiagnosticReport,
    DiagnosticsCollector,
    SIPState,
)
from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.core.settings import (
    AppSettings,
)
from tcc_permission_assistant.core.update_badge import UpdateBadgeManager
from tcc_permission_assistant.gui.about_dialog import AboutDialog
from tcc_permission_assistant.gui.batch_page import BatchPage
from tcc_permission_assistant.gui.components import action_button
from tcc_permission_assistant.gui.diagnostics_page import DiagnosticsPage
from tcc_permission_assistant.gui.dynamic_permissions_page import (
    DynamicPermissionsPage,
)
from tcc_permission_assistant.gui.efi_page import EFIPage
from tcc_permission_assistant.gui.icons import load_icon
from tcc_permission_assistant.gui.log_page import LogPage
from tcc_permission_assistant.gui.restore_page import RestorePage
from tcc_permission_assistant.gui.scan_page import ScanPage
from tcc_permission_assistant.gui.settings_page import SettingsPage
from tcc_permission_assistant.gui.theme import COLORS
from tcc_permission_assistant.gui.update_badge_page import UpdateBadgePage

PERMISSION_NAVIGATION_ITEMS = (
    ("扫描", "scan-search"),
    ("批量", "list-checks"),
    ("动态权限", "list-checks"),
    ("恢复", "archive-restore"),
    ("诊断", "stethoscope"),
    ("日志", "scroll-text"),
)

SYSTEM_NAVIGATION_ITEMS = (
    (UPDATE_BADGE_PAGE_NAME, "bell-dot"),
    (EFI_PAGE_NAME, "hard-drive"),
)


class MainWindow(QMainWindow):
    window_closed = pyqtSignal()

    def __init__(
        self,
        audit: AuditLogger,
        parent: QWidget | None = None,
        *,
        settings: AppSettings | None = None,
        inventory: tuple[object, ...] | None = None,
        inventory_errors: tuple[tuple[object, str], ...] = (),
    ) -> None:
        super().__init__(parent)
        self.audit = audit
        self.settings = settings or AppSettings()
        self.badge_manager = UpdateBadgeManager()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(load_icon("tool-case", COLORS["accent"], 32))
        self.resize(1240, 820)
        self.setMinimumSize(1040, 700)

        self.scan_page = ScanPage(
            audit,
            display_language=self.settings.application_name_language,
        )
        self.batch_page = BatchPage(
            audit,
            app_name_language=self.settings.application_name_language,
        )
        if inventory is not None:
            self.batch_page.set_preloaded_inventory(
                inventory,
                inventory_errors,
            )
        self.dynamic_page = DynamicPermissionsPage(audit)
        if inventory is not None:
            self.dynamic_page.set_preloaded_inventory(
                inventory,
                inventory_errors,
            )
        self.restore_page = RestorePage(audit)
        self.diagnostics_page = DiagnosticsPage(audit)
        self.log_page = LogPage(audit)
        self.update_badge_page = UpdateBadgePage(audit, self.badge_manager)
        self.efi_page = EFIPage(audit)
        self.settings_page = SettingsPage(self.settings, audit)
        self._build_ui()
        self._build_menu()
        self._connect_pages()
        self._badge_clear_timer = QTimer(self)
        self._badge_clear_timer.setInterval(6 * 60 * 60 * 1000)
        self._badge_clear_timer.timeout.connect(self._auto_clear_update_badges)
        self._auto_clear_running = False
        self._configure_auto_clear()
        QTimer.singleShot(0, self._refresh_environment_status)

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("contentRoot")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(196)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(15, 20, 15, 16)
        sidebar_layout.setSpacing(5)

        brand_row = QHBoxLayout()
        brand_icon = QLabel()
        brand_icon.setPixmap(load_icon("tool-case", "#7BD1DA", 30).pixmap(30, 30))
        brand_icon.setFixedSize(34, 34)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        brand_title = QLabel(APP_SHORT_NAME)
        brand_title.setObjectName("brandTitle")
        brand_caption = QLabel(APP_CAPTION)
        brand_caption.setObjectName("brandCaption")
        brand_text.addWidget(brand_title)
        brand_text.addWidget(brand_caption)
        brand_row.addWidget(brand_icon)
        brand_row.addLayout(brand_text, 1)
        sidebar_layout.addLayout(brand_row)
        sidebar_layout.addSpacing(20)

        caption = QLabel("工具箱")
        caption.setObjectName("sidebarCaption")
        sidebar_layout.addWidget(caption)
        sidebar_layout.addSpacing(3)

        module_row = QWidget()
        module_layout = QHBoxLayout(module_row)
        module_layout.setContentsMargins(0, 0, 0, 0)
        module_layout.setSpacing(2)
        self.module_button = QPushButton(PERMISSION_MODULE_NAME)
        self.module_button.setObjectName("moduleButton")
        self.module_button.setIcon(load_icon("shield-check", "#7BD1DA", 17))
        self.module_button.setIconSize(QSize(17, 17))
        self.module_button.setToolTip(PERMISSION_MODULE_DESCRIPTION)
        self.module_button.setCursor(Qt.CursorShape.PointingHandCursor)
        module_layout.addWidget(self.module_button, 1)
        self.disclosure_button = QPushButton()
        self.disclosure_button.setObjectName("disclosure")
        self.disclosure_button.setIcon(load_icon("chevron-down", "#8EB3BB", 16))
        self.disclosure_button.setIconSize(QSize(16, 16))
        self.disclosure_button.setFixedSize(26, 26)
        self.disclosure_button.setCursor(Qt.CursorShape.PointingHandCursor)
        module_layout.addWidget(self.disclosure_button)
        sidebar_layout.addWidget(module_row)

        self.nav_container = QWidget()
        nav_layout = QVBoxLayout(self.nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(3)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, (title, icon_name) in enumerate(PERMISSION_NAVIGATION_ITEMS):
            button = QPushButton(title)
            button.setObjectName("navButton")
            button.setProperty("nested", True)
            button.setCheckable(True)
            button.setIcon(load_icon(icon_name, "#8EB3BB", 18))
            button.setIconSize(QSize(18, 18))
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked, i=index: self.go_to(i))
            self.nav_group.addButton(button, index)
            nav_layout.addWidget(button)
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda i=index: self.go_to(i))
        sidebar_layout.addWidget(self.nav_container)
        self._module_expanded = True
        self.module_button.clicked.connect(self.toggle_permission_module)
        self.disclosure_button.clicked.connect(self.toggle_permission_module)
        sidebar_layout.addSpacing(7)

        system_module_row = QWidget()
        system_module_layout = QHBoxLayout(system_module_row)
        system_module_layout.setContentsMargins(0, 0, 0, 0)
        system_module_layout.setSpacing(2)
        self.system_module_button = QPushButton(SYSTEM_MODULE_NAME)
        self.system_module_button.setObjectName("moduleButton")
        self.system_module_button.setIcon(load_icon("wrench", "#7BD1DA", 17))
        self.system_module_button.setIconSize(QSize(17, 17))
        self.system_module_button.setToolTip("系统更新提示与维护")
        self.system_module_button.setCursor(Qt.CursorShape.PointingHandCursor)
        system_module_layout.addWidget(self.system_module_button, 1)
        self.system_disclosure_button = QPushButton()
        self.system_disclosure_button.setObjectName("disclosure")
        self.system_disclosure_button.setIcon(load_icon("chevron-down", "#8EB3BB", 16))
        self.system_disclosure_button.setIconSize(QSize(16, 16))
        self.system_disclosure_button.setFixedSize(26, 26)
        self.system_disclosure_button.setCursor(Qt.CursorShape.PointingHandCursor)
        system_module_layout.addWidget(self.system_disclosure_button)
        sidebar_layout.addWidget(system_module_row)

        self.system_nav_container = QWidget()
        system_nav_layout = QVBoxLayout(self.system_nav_container)
        system_nav_layout.setContentsMargins(0, 0, 0, 0)
        system_nav_layout.setSpacing(3)
        system_index = len(PERMISSION_NAVIGATION_ITEMS)
        for offset, (title, icon_name) in enumerate(SYSTEM_NAVIGATION_ITEMS):
            index = system_index + offset
            system_button = QPushButton(title)
            system_button.setObjectName("navButton")
            system_button.setProperty("nested", True)
            system_button.setCheckable(True)
            system_button.setIcon(load_icon(icon_name, "#8EB3BB", 18))
            system_button.setIconSize(QSize(18, 18))
            system_button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            system_button.setCursor(Qt.CursorShape.PointingHandCursor)
            system_button.clicked.connect(lambda _checked, i=index: self.go_to(i))
            self.nav_group.addButton(system_button, index)
            system_nav_layout.addWidget(system_button)
            system_shortcut = QShortcut(
                QKeySequence(f"Ctrl+{index + 1}"),
                self,
            )
            system_shortcut.activated.connect(lambda i=index: self.go_to(i))
        sidebar_layout.addWidget(self.system_nav_container)
        self._system_expanded = True
        self.system_module_button.clicked.connect(self.toggle_system_module)
        self.system_disclosure_button.clicked.connect(self.toggle_system_module)

        settings_index = system_index + len(SYSTEM_NAVIGATION_ITEMS)
        self.settings_button = QPushButton("设置")
        self.settings_button.setObjectName("navButton")
        self.settings_button.setCheckable(True)
        self.settings_button.setIcon(load_icon("settings", "#8EB3BB", 18))
        self.settings_button.setIconSize(QSize(18, 18))
        self.settings_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(
            lambda _checked: self.go_to(settings_index)
        )
        self.nav_group.addButton(self.settings_button, settings_index)
        sidebar_layout.addWidget(self.settings_button)
        settings_shortcut = QShortcut(
            QKeySequence(f"Ctrl+{settings_index + 1}"),
            self,
        )
        settings_shortcut.activated.connect(lambda: self.go_to(settings_index))

        sidebar_layout.addStretch(1)

        self.about_button = action_button(
            f"关于{APP_SHORT_NAME}",
            "info",
            tooltip=f"开发者：{DEVELOPER_NAME}",
        )
        self.about_button.setObjectName("sidebarAboutButton")
        self.about_button.setIcon(load_icon("info", COLORS["sidebar_muted"], 15))
        self.about_button.clicked.connect(self.show_about)
        sidebar_layout.addWidget(self.about_button)
        sidebar_layout.addSpacing(8)

        environment_caption = QLabel("环境")
        environment_caption.setObjectName("sidebarCaption")
        sidebar_layout.addWidget(environment_caption)
        self.sidebar_sip = QLabel("SIP  读取中")
        self.sidebar_sip.setStyleSheet(
            f"color: {COLORS['sidebar_muted']}; font-size: 11px; padding: 3px 1px;"
        )
        self.sidebar_db = QLabel("TCC.db  检查中")
        self.sidebar_db.setStyleSheet(
            f"color: {COLORS['sidebar_muted']}; font-size: 11px; padding: 3px 1px;"
        )
        sidebar_layout.addWidget(self.sidebar_sip)
        sidebar_layout.addWidget(self.sidebar_db)
        sidebar_layout.addSpacing(8)
        version_label = QLabel(f"v{__version__} · 用户级优先")
        version_label.setObjectName("brandCaption")
        sidebar_layout.addWidget(version_label)
        root.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.stack = QStackedWidget()
        for page in (
            self.scan_page,
            self.batch_page,
            self.dynamic_page,
            self.restore_page,
            self.diagnostics_page,
            self.log_page,
            self.update_badge_page,
            self.efi_page,
            self.settings_page,
        ):
            self.stack.addWidget(page)
        content_layout.addWidget(self.stack, 1)
        root.addWidget(content, 1)

        self.status_bar = self.statusBar()
        self.status_bar.setObjectName("statusBar")
        self.status_bar.setSizeGripEnabled(False)
        self.status_sip = QLabel("SIP：检查中")
        self.status_database = QLabel("数据库：检查中")
        self.status_mode = QLabel("操作模式：只读优先")
        self.status_bar.addWidget(self.status_sip)
        self.status_bar.addWidget(self.status_database)
        self.status_bar.addPermanentWidget(self.status_mode)

        self.go_to(0)

    def _build_menu(self) -> None:
        self.about_action = QAction(f"关于 {APP_NAME}", self)
        self.about_action.setMenuRole(QAction.MenuRole.AboutRole)
        self.about_action.triggered.connect(self.show_about)
        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction(self.about_action)

    def show_about(self) -> None:
        dialog = AboutDialog(self)
        self.about_dialog = dialog
        dialog.exec()

    def _connect_pages(self) -> None:
        self.scan_page.scan_completed.connect(self.dynamic_page.set_scan_result)
        self.scan_page.open_dynamic_permissions_requested.connect(lambda: self.go_to(2))
        self.dynamic_page.environment_changed.connect(self._refresh_environment_status)
        self.restore_page.environment_changed.connect(self._refresh_environment_status)
        self.diagnostics_page.environment_updated.connect(self._apply_diagnostic_status)
        self.settings_page.application_name_language_changed.connect(
            self._apply_app_name_language
        )
        self.settings_page.settings_changed.connect(self._configure_auto_clear)

    def _apply_app_name_language(self, language: str) -> None:
        self.scan_page.set_app_name_language(language)
        self.batch_page.set_app_name_language(language)

    def _configure_auto_clear(self) -> None:
        if self.settings.auto_clear_update_badges:
            self._badge_clear_timer.start()
            QTimer.singleShot(1200, self._auto_clear_update_badges)
        else:
            self._badge_clear_timer.stop()

    def _auto_clear_update_badges(self) -> None:
        if not self.settings.auto_clear_update_badges or self._auto_clear_running:
            return
        self._auto_clear_running = True
        try:
            snapshot = self.badge_manager.read()
            keys = tuple(item.bundle_id for item in snapshot.update_items)
            if keys:
                result = self.badge_manager.clear_badges(
                    keys,
                    restart_ui=True,
                )
                self.audit.event(
                    "auto_clear_update_badge",
                    keys=list(result.cleared_keys),
                    backup_path=result.backup.path,
                )
        except Exception as exc:
            self.audit.event(
                "auto_clear_update_badge_error",
                error_type=type(exc).__name__,
                error=str(exc),
            )
        finally:
            self._auto_clear_running = False

    def go_to(self, index: int) -> None:
        permission_count = len(PERMISSION_NAVIGATION_ITEMS)
        system_end = permission_count + len(SYSTEM_NAVIGATION_ITEMS)
        if index < permission_count and not self._module_expanded:
            self._set_module_expanded(True)
        if permission_count <= index < system_end and not self._system_expanded:
            self._set_system_expanded(True)
        self.stack.setCurrentIndex(index)
        button = self.nav_group.button(index)
        if button is not None:
            button.setChecked(True)
        if index == 5:
            self.log_page.refresh()

    def toggle_permission_module(self) -> None:
        self._set_module_expanded(not self._module_expanded)

    def toggle_system_module(self) -> None:
        self._set_system_expanded(not self._system_expanded)

    def _set_module_expanded(self, expanded: bool) -> None:
        self._module_expanded = expanded
        self.nav_container.setVisible(expanded)
        self.disclosure_button.setIcon(
            load_icon(
                "chevron-down" if expanded else "chevron-right",
                "#8EB3BB",
                16,
            )
        )
        self.module_button.setToolTip(
            PERMISSION_MODULE_DESCRIPTION
            if expanded
            else f"{PERMISSION_MODULE_DESCRIPTION}（已折叠）"
        )

    def _set_system_expanded(self, expanded: bool) -> None:
        self._system_expanded = expanded
        self.system_nav_container.setVisible(expanded)
        self.system_disclosure_button.setIcon(
            load_icon(
                "chevron-down" if expanded else "chevron-right",
                "#8EB3BB",
                16,
            )
        )

    def closeEvent(self, event) -> None:
        self.audit.event(
            "gui_window_close",
            visible=self.isVisible(),
            minimized=self.isMinimized(),
        )
        self.batch_page.shutdown()
        self.dynamic_page.shutdown()
        super().closeEvent(event)
        self.window_closed.emit()

    def _refresh_environment_status(self) -> None:
        try:
            report = DiagnosticsCollector().collect(advanced=False)
        except Exception:
            self.sidebar_sip.setText("SIP  读取失败")
            self.sidebar_db.setText("TCC.db  读取失败")
            self.status_sip.setText("SIP：读取失败")
            self.status_database.setText("数据库：读取失败")
            return
        self._apply_diagnostic_status(report)

    def _apply_diagnostic_status(self, report: DiagnosticReport) -> None:
        sip_labels = {
            SIPState.ENABLED: "已启用",
            SIPState.DISABLED: "已关闭",
            SIPState.UNKNOWN: "自定义",
            SIPState.ERROR: "未知",
        }
        sip_text = sip_labels[report.sip.state]
        if report.user_database.schema_readable:
            db_text = "可写" if report.user_database.posix_writable else "只读"
        elif report.user_database.exists:
            db_text = "不可读"
        else:
            db_text = "不存在"
        self.sidebar_sip.setText(f"SIP  {sip_text}")
        self.sidebar_db.setText(f"TCC.db  {db_text}")
        self.status_sip.setText(f"SIP：{sip_text}")
        self.status_database.setText(f"用户级 TCC.db：{db_text}")
        if report.warnings:
            self.status_mode.setText(f"环境警告：{len(report.warnings)} 项")
        else:
            self.status_mode.setText("操作模式：只读优先")
