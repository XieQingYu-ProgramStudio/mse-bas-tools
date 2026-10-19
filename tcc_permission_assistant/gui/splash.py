"""Office-style startup splash that preloads the permission module."""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from tcc_permission_assistant.branding import (
    APP_NAME,
    PERMISSION_MODULE_DESCRIPTION,
)
from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.core.settings import AppSettings
from tcc_permission_assistant.gui.app_inventory import AppInventoryWorker
from tcc_permission_assistant.gui.icons import load_icon
from tcc_permission_assistant.gui.main_window import MainWindow
from tcc_permission_assistant.gui.theme import COLORS


class StartupSplash(QWidget):
    """A compact, animated preflight window."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(440, 272)
        self._entrance_animation: QPropertyAnimation | None = None
        self._pulse_timer: QTimer | None = None
        self._pulse_index = 0
        self._fade_animation: QPropertyAnimation | None = None
        self._icon_pixmaps = [
            load_icon("tool-case", COLORS["accent"], size).pixmap(size, size)
            for size in (30, 32, 34, 36, 38, 36, 34, 32)
        ]
        self._build_ui()
        self._center_on_screen()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        frame = QFrame()
        frame.setObjectName("splashFrame")
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(COLORS["ink"]))
        frame.setGraphicsEffect(shadow)
        outer.addWidget(frame)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(30, 27, 30, 24)
        layout.setSpacing(10)

        icon_tile = QFrame()
        icon_tile.setObjectName("splashIconTile")
        icon_tile.setFixedSize(58, 58)
        icon_layout = QHBoxLayout(icon_tile)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        self.icon_label = QLabel()
        self.icon_label.setPixmap(self._icon_pixmaps[0])
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(self.icon_label)
        layout.addWidget(icon_tile, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(3)

        self.title_label = QLabel(APP_NAME)
        self.title_label.setObjectName("splashTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        self.caption_label = QLabel(PERMISSION_MODULE_DESCRIPTION)
        self.caption_label.setObjectName("splashCaption")
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.caption_label)
        layout.addStretch(1)

        self.progress = QProgressBar()
        self.progress.setObjectName("splashProgress")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.status_label = QLabel("正在准备权限管理…")
        self.status_label.setObjectName("splashStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self.move(geometry.center() - self.rect().center())

    def show_animated(self) -> None:
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        entrance = QPropertyAnimation(self, b"windowOpacity", self)
        entrance.setDuration(260)
        entrance.setStartValue(0.0)
        entrance.setEndValue(1.0)
        entrance.setEasingCurve(QEasingCurve.Type.OutCubic)
        entrance.start()
        self._entrance_animation = entrance
        self._start_icon_pulse()

    def _start_icon_pulse(self) -> None:
        timer = QTimer(self)
        timer.setInterval(105)
        timer.timeout.connect(self._advance_icon_pulse)
        timer.start()
        self._pulse_timer = timer

    def _advance_icon_pulse(self) -> None:
        self._pulse_index = (self._pulse_index + 1) % len(self._icon_pixmaps)
        self.icon_label.setPixmap(self._icon_pixmaps[self._pulse_index])

    def update_scan_progress(
        self,
        index: int,
        total: int,
        name: str,
    ) -> None:
        if total <= 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, total)
            self.progress.setValue(index)
        self.status_label.setText(f"正在扫描应用权限 · {index}/{total} · {name}")

    def set_finishing(self, app_count: int) -> None:
        if self._pulse_timer is not None:
            self._pulse_timer.stop()
            self._pulse_timer = None
        self.icon_label.setPixmap(
            load_icon("tool-case", COLORS["accent"], 34).pixmap(34, 34)
        )
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.status_label.setText(f"扫描完成 · {app_count} 个应用 · 正在打开工具箱")

    def fade_out(self, on_finished=None) -> None:
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(190)
        animation.setStartValue(self.windowOpacity())
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.InCubic)
        if on_finished is not None:
            animation.finished.connect(on_finished)
        animation.start()
        self._fade_animation = animation


class StartupController(QObject):
    """Coordinate preflight scanning, splash animation, and main-window handoff."""

    def __init__(
        self,
        app: QApplication,
        audit: AuditLogger,
        *,
        settings: AppSettings | None = None,
        worker_factory=None,
    ) -> None:
        super().__init__()
        self.app = app
        self.audit = audit
        self.settings = settings or AppSettings()
        self.splash = StartupSplash()
        self.window: MainWindow | None = None
        self.worker: AppInventoryWorker | None = None
        self.results: tuple[object, ...] = ()
        self.errors: tuple[tuple[object, str], ...] = ()
        self._scan_ready = False
        self._minimum_elapsed = False
        self._finishing = False
        self._worker_factory = worker_factory or (
            lambda: AppInventoryWorker(
                self.audit,
                display_language=self.settings.application_name_language,
            )
        )
        app.aboutToQuit.connect(self.shutdown)
        app.aboutToQuit.connect(
            lambda: self.audit.event(
                "app_quit",
                window_created=self.window is not None,
                window_visible=(
                    self.window.isVisible() if self.window is not None else False
                ),
            )
        )

    def start(self) -> None:
        self.app.setQuitOnLastWindowClosed(False)
        self.splash.show_animated()
        worker = self._worker_factory()
        worker.progress.connect(self.splash.update_scan_progress)
        worker.loaded.connect(self._scan_loaded)
        worker.finished.connect(self._scan_finished)
        self.worker = worker
        QTimer.singleShot(1200, self._minimum_time_elapsed)
        worker.start()

    def _minimum_time_elapsed(self) -> None:
        self._minimum_elapsed = True
        self._finish_if_ready()

    def _scan_loaded(self, payload: object) -> None:
        self.results, self.errors = payload
        self._scan_ready = True
        self._finish_if_ready()

    def _scan_finished(self) -> None:
        if not self._scan_ready:
            self.results = ()
            self.errors = (("inventory", "应用扫描未返回结果"),)
            self._scan_ready = True
            self._finish_if_ready()
        self.worker = None

    def _finish_if_ready(self) -> None:
        if not self._scan_ready or not self._minimum_elapsed or self._finishing:
            return
        self._finishing = True
        self.splash.set_finishing(len(self.results))
        QTimer.singleShot(320, self._show_main_window)

    def _show_main_window(self) -> None:
        self.window = MainWindow(
            self.audit,
            settings=self.settings,
            inventory=self.results,
            inventory_errors=self.errors,
        )
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.window.window_closed.connect(self.app.quit)
        self.splash.fade_out(self._splash_closed)

    def _splash_closed(self) -> None:
        self.splash.close()

    def shutdown(self) -> None:
        worker = self.worker
        if worker is None or not worker.isRunning():
            self.app.setQuitOnLastWindowClosed(True)
            return
        worker.requestInterruption()
        worker.wait()
        self.worker = None
        self.app.setQuitOnLastWindowClosed(True)
