"""Application preferences page."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from tcc_permission_assistant.core.autostart import (
    AutoStartError,
    AutoStartManager,
)
from tcc_permission_assistant.core.localization import system_languages
from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.core.settings import (
    LANGUAGE_EN,
    LANGUAGE_SYSTEM,
    LANGUAGE_ZH_HANS,
    AppSettings,
)
from tcc_permission_assistant.gui.components import (
    action_button,
    page_header,
    panel,
    section_title,
)


class SettingsPage(QWidget):
    application_name_language_changed = pyqtSignal(str)
    settings_changed = pyqtSignal()

    def __init__(
        self,
        settings: AppSettings,
        audit: AuditLogger,
        parent: QWidget | None = None,
        *,
        autostart_manager: AutoStartManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.audit = audit
        self.autostart = autostart_manager or AutoStartManager()
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(14)

        header, _ = page_header(
            "设置",
            "应用名称 · 启动 · 自动化 · 界面中文",
        )
        root.addWidget(header)

        language_panel, language_layout = panel()
        language_layout.addWidget(section_title("应用名称语言"))
        description = QLabel("用于读取应用自带的本地化名称，例如“微信”和“飞书”。")
        description.setObjectName("muted")
        description.setWordWrap(True)
        language_layout.addWidget(description)

        controls = QHBoxLayout()
        self.language_combo = QComboBox()
        self.language_combo.addItem("跟随系统", LANGUAGE_SYSTEM)
        self.language_combo.addItem("简体中文", LANGUAGE_ZH_HANS)
        self.language_combo.addItem("English", LANGUAGE_EN)
        self.language_combo.setMinimumWidth(220)
        self.language_combo.currentIndexChanged.connect(self._update_language_preview)
        controls.addWidget(self.language_combo)
        controls.addStretch(1)
        save_button = action_button(
            "保存设置",
            "file-down",
            role="primary",
        )
        save_button.clicked.connect(self.save)
        controls.addWidget(save_button)
        language_layout.addLayout(controls)

        system_text = "、".join(system_languages())
        self.system_language_label = QLabel(f"系统首选语言：{system_text}")
        self.system_language_label.setObjectName("muted")
        language_layout.addWidget(self.system_language_label)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("value")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        language_layout.addWidget(self.preview_label)

        settings_path = QLabel(f"设置文件：{self.settings.path}")
        settings_path.setObjectName("mono")
        settings_path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        language_layout.addWidget(settings_path)
        root.addWidget(language_panel)

        automation_panel, automation_layout = panel()
        automation_layout.addWidget(section_title("启动与自动化"))
        self.auto_clear_checkbox = QCheckBox("自动清理设置中的系统更新红点")
        self.auto_clear_checkbox.setToolTip(
            "应用启动时以及运行期间每 6 小时检查一次，只清理更新相关红点。"
        )
        automation_layout.addWidget(self.auto_clear_checkbox)
        self.autostart_checkbox = QCheckBox("登录时自动启动月星BAS工具箱")
        automation_layout.addWidget(self.autostart_checkbox)
        self.autostart_status = QLabel()
        self.autostart_status.setObjectName("muted")
        self.autostart_status.setWordWrap(True)
        automation_layout.addWidget(self.autostart_status)
        self.prepare_permissions_checkbox = QCheckBox(
            "启动时自动写入本软件摄像头和麦克风权限"
        )
        self.prepare_permissions_checkbox.setToolTip(
            "适用于无法弹出原生 TCC 授权的黑苹果环境；只写入本软件自身权限。"
        )
        automation_layout.addWidget(self.prepare_permissions_checkbox)
        root.addWidget(automation_panel)

        boundary = QFrame()
        boundary.setObjectName("warningBox")
        boundary_layout = QVBoxLayout(boundary)
        boundary_layout.setContentsMargins(14, 10, 14, 10)
        boundary_text = QLabel(
            "macOS 原生权限请求窗口由系统 tccd 管理。"
            "工具箱不会拦截、伪装或代替系统弹窗执行同意与拒绝。"
        )
        boundary_text.setWordWrap(True)
        boundary_layout.addWidget(boundary_text)
        root.addWidget(boundary)
        root.addStretch(1)

        self.sync_from_settings()

    def sync_from_settings(self) -> None:
        index = self.language_combo.findData(self.settings.application_name_language)
        self.language_combo.setCurrentIndex(max(index, 0))
        self._update_language_preview()
        self.auto_clear_checkbox.setChecked(self.settings.auto_clear_update_badges)
        autostart_available = self.autostart.availability_error is None
        autostart_enabled = self.autostart.is_enabled
        self.autostart_checkbox.setChecked(autostart_enabled)
        self.prepare_permissions_checkbox.setChecked(
            self.settings.prepare_hardware_permissions_at_launch
        )
        self.autostart_checkbox.setEnabled(autostart_available or autostart_enabled)
        self.autostart_status.setText(
            self.autostart.availability_error
            or (
                "登录启动项已启用，将在下次登录时生效。"
                if autostart_enabled
                else "登录启动项未启用。"
            )
        )

    def _update_language_preview(self) -> None:
        language = self.language_combo.currentData()
        if language == LANGUAGE_EN:
            sample = "WeChat、Lark"
        elif language == LANGUAGE_ZH_HANS or language == LANGUAGE_SYSTEM:
            sample = "微信、飞书"
        else:
            sample = "—"
        self.preview_label.setText(f"名称示例：{sample}")

    def save(self) -> None:
        language = str(self.language_combo.currentData())
        previous = self.settings.application_name_language
        launch_at_login = self.autostart_checkbox.isChecked()
        try:
            if launch_at_login and not self.autostart.is_enabled:
                self.autostart.enable()
            elif not launch_at_login:
                self.autostart.disable()
            self.settings.update_preferences(
                application_name_language=language,
                auto_clear_update_badges=(self.auto_clear_checkbox.isChecked()),
                launch_at_login=launch_at_login,
                prepare_hardware_permissions_at_launch=(
                    self.prepare_permissions_checkbox.isChecked()
                ),
            )
        except (AutoStartError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "保存设置失败", str(exc))
            return
        self.audit.event(
            "settings_update",
            application_name_language=language,
            auto_clear_update_badges=(self.settings.auto_clear_update_badges),
            launch_at_login=self.settings.launch_at_login,
            prepare_hardware_permissions_at_launch=(
                self.settings.prepare_hardware_permissions_at_launch
            ),
            previous=previous,
        )
        if language != previous:
            self.application_name_language_changed.emit(language)
        self.settings_changed.emit()
        self.sync_from_settings()
        QMessageBox.information(
            self,
            "设置已保存",
            "设置已保存。登录启动项的变更将在下次登录时生效。",
        )
