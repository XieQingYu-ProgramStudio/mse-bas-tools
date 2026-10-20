"""Hardware and TCC self-test page."""

from __future__ import annotations

import math
import struct
import sys
from array import array

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import (
    QAudioFormat,
    QAudioSink,
    QAudioSource,
    QCamera,
    QMediaCaptureSession,
    QMediaDevices,
    QVideoSink,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tcc_permission_assistant.core.backup import BackupManager
from tcc_permission_assistant.core.logger import AuditLogger
from tcc_permission_assistant.core.models import (
    PermissionStatus,
    TCCDatabaseScope,
    TCCService,
)
from tcc_permission_assistant.core.self_permissions import (
    SELF_BUNDLE_ID,
    ensure_self_permissions,
)
from tcc_permission_assistant.core.tcc_db import TCCDatabase
from tcc_permission_assistant.gui.components import (
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


class SystemTestPage(QWidget):
    """Test camera, microphone, speaker, and the app's own TCC permissions."""

    environment_changed = pyqtSignal()

    def __init__(
        self,
        audit: AuditLogger,
        database: TCCDatabase | None = None,
        backup_manager: BackupManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.audit = audit
        self.database = database or TCCDatabase.for_scope(TCCDatabaseScope.USER)
        self.backup_manager = backup_manager or BackupManager()
        self._camera: QCamera | None = None
        self._capture_session: QMediaCaptureSession | None = None
        self._video_sink: QVideoSink | None = None
        self._audio_source: QAudioSource | None = None
        self._audio_device = None
        self._audio_level_timer: QTimer | None = None
        self._audio_sample_format = QAudioFormat.SampleFormat.Int16
        self._speaker_sink: QAudioSink | None = None
        self._speaker_buffer: QBuffer | None = None
        self._speaker_timer: QTimer | None = None
        self._permission_prepare = False
        self._prepare_camera_done = False
        self._prepare_microphone_done = False
        self._prepare_timeout: QTimer | None = None
        self._prepare_finishing = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(12)

        refresh_button = action_button("刷新设备", "refresh-cw")
        refresh_button.clicked.connect(self.refresh)
        prepare_button = action_button(
            "写入本软件权限",
            "shield-check",
            role="primary",
        )
        prepare_button.clicked.connect(self.prepare_system_permissions)
        header, _ = page_header(
            "系统测试",
            "摄像头 · 麦克风 · 扬声器 · 原生 TCC 授权",
            [refresh_button, prepare_button],
        )
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        permission_panel, permission_layout = panel()
        permission_header = QHBoxLayout()
        permission_header.addWidget(section_title("本软件系统权限"))
        permission_header.addStretch(1)
        permission_layout.addLayout(permission_header)
        permission_row = QHBoxLayout()
        permission_row.addWidget(QLabel("摄像头"))
        self.camera_permission_badge = status_badge("未知", "unknown")
        permission_row.addWidget(self.camera_permission_badge)
        permission_row.addSpacing(18)
        permission_row.addWidget(QLabel("麦克风"))
        self.microphone_permission_badge = status_badge("未知", "unknown")
        permission_row.addWidget(self.microphone_permission_badge)
        permission_row.addStretch(1)
        self.permission_status = QLabel("黑苹果环境可直接写入本软件用户级 TCC 权限。")
        self.permission_status.setObjectName("muted")
        self.permission_status.setWordWrap(True)
        permission_row.addWidget(self.permission_status, 1)
        permission_layout.addLayout(permission_row)
        content_layout.addWidget(permission_panel)

        camera_panel, camera_layout = panel()
        camera_header = QHBoxLayout()
        camera_header.addWidget(section_title("摄像头测试"))
        camera_header.addStretch(1)
        self.camera_device_label = QLabel("正在读取摄像头")
        self.camera_device_label.setObjectName("muted")
        camera_header.addWidget(self.camera_device_label)
        self.camera_start_button = action_button("开始预览", "camera", role="primary")
        self.camera_start_button.clicked.connect(self.start_camera)
        camera_header.addWidget(self.camera_start_button)
        self.camera_stop_button = action_button("停止", "x-circle")
        self.camera_stop_button.setEnabled(False)
        self.camera_stop_button.clicked.connect(self.stop_camera)
        camera_header.addWidget(self.camera_stop_button)
        camera_layout.addLayout(camera_header)
        self.camera_preview = QLabel("摄像头画面将在这里显示")
        self.camera_preview.setObjectName("muted")
        self.camera_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_preview.setMinimumSize(480, 250)
        self.camera_preview.setStyleSheet(
            "background: #0A1728; color: #A9B6BE; border-radius: 5px;"
        )
        camera_layout.addWidget(self.camera_preview, 1)
        self.camera_status = QLabel("未开始")
        self.camera_status.setObjectName("muted")
        self.camera_status.setWordWrap(True)
        camera_layout.addWidget(self.camera_status)
        content_layout.addWidget(camera_panel, 1)

        audio_row = QHBoxLayout()
        microphone_panel, microphone_layout = panel()
        microphone_header = QHBoxLayout()
        microphone_header.addWidget(section_title("麦克风测试"))
        microphone_header.addStretch(1)
        self.microphone_device_label = QLabel("正在读取麦克风")
        self.microphone_device_label.setObjectName("muted")
        microphone_header.addWidget(self.microphone_device_label)
        microphone_layout.addLayout(microphone_header)
        self.microphone_level = QProgressBar()
        self.microphone_level.setObjectName("levelMeter")
        self.microphone_level.setRange(0, 100)
        self.microphone_level.setValue(0)
        self.microphone_level.setFormat("输入电平 0%")
        microphone_layout.addWidget(self.microphone_level)
        microphone_buttons = QHBoxLayout()
        self.microphone_start_button = action_button(
            "开始检测",
            "camera",
            role="primary",
        )
        self.microphone_start_button.clicked.connect(self.start_microphone)
        microphone_buttons.addWidget(self.microphone_start_button)
        self.microphone_stop_button = action_button("停止", "x-circle")
        self.microphone_stop_button.setEnabled(False)
        self.microphone_stop_button.clicked.connect(self.stop_microphone)
        microphone_buttons.addWidget(self.microphone_stop_button)
        microphone_buttons.addStretch(1)
        microphone_layout.addLayout(microphone_buttons)
        self.microphone_status = QLabel("点击开始检测并说话，观察电平变化。")
        self.microphone_status.setObjectName("muted")
        self.microphone_status.setWordWrap(True)
        microphone_layout.addWidget(self.microphone_status)
        audio_row.addWidget(microphone_panel, 1)

        speaker_panel, speaker_layout = panel()
        speaker_layout.addWidget(section_title("扬声器测试"))
        self.speaker_device_label = QLabel("正在读取扬声器")
        self.speaker_device_label.setObjectName("muted")
        self.speaker_device_label.setWordWrap(True)
        speaker_layout.addWidget(self.speaker_device_label)
        self.speaker_button = action_button(
            "播放测试音",
            "volume-2",
            role="primary",
        )
        self.speaker_button.clicked.connect(self.play_test_tone)
        speaker_layout.addWidget(self.speaker_button)
        self.speaker_status = QLabel("将播放约 0.8 秒的 440 Hz 测试音。")
        self.speaker_status.setObjectName("muted")
        self.speaker_status.setWordWrap(True)
        speaker_layout.addWidget(self.speaker_status)
        speaker_layout.addStretch(1)
        audio_row.addWidget(speaker_panel, 1)
        content_layout.addLayout(audio_row)
        content_layout.addStretch(1)

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def hideEvent(self, event) -> None:
        self.stop_all()
        super().hideEvent(event)

    def shutdown(self) -> None:
        self.stop_all()

    def refresh(self) -> None:
        self._refresh_devices()
        self.refresh_permission_status()

    def _refresh_devices(self) -> None:
        camera = QMediaDevices.defaultVideoInput()
        self.camera_device_label.setText(
            camera.description() if not camera.isNull() else "未检测到摄像头"
        )
        microphone = QMediaDevices.defaultAudioInput()
        self.microphone_device_label.setText(
            microphone.description() if not microphone.isNull() else "未检测到麦克风"
        )
        speaker = QMediaDevices.defaultAudioOutput()
        self.speaker_device_label.setText(
            speaker.description() if not speaker.isNull() else "未检测到扬声器"
        )

    def refresh_permission_status(self) -> None:
        try:
            statuses = permission_statuses(
                SELF_BUNDLE_ID,
                [TCCService.CAMERA, TCCService.MICROPHONE],
                database=self.database,
            )
        except Exception as exc:
            self._set_permission_badge(
                self.camera_permission_badge,
                PermissionStatus.UNKNOWN,
            )
            self._set_permission_badge(
                self.microphone_permission_badge,
                PermissionStatus.UNKNOWN,
            )
            self.permission_status.setText(f"无法读取本软件 TCC 状态：{exc}")
            return
        self._set_permission_badge(
            self.camera_permission_badge,
            statuses.get(TCCService.CAMERA, PermissionStatus.UNKNOWN),
        )
        self._set_permission_badge(
            self.microphone_permission_badge,
            statuses.get(TCCService.MICROPHONE, PermissionStatus.UNKNOWN),
        )
        self.permission_status.setText("点击“写入本软件权限”可注册摄像头和麦克风访问。")

    @staticmethod
    def _set_permission_badge(label: QLabel, status: PermissionStatus) -> None:
        label.setText(STATUS_LABELS[status])
        label.setProperty("badge", STATUS_BADGE_STATES[status])
        label.style().unpolish(label)
        label.style().polish(label)

    def prepare_system_permissions(self) -> None:
        permission_text = ""
        permission_ready = False
        try:
            grant = ensure_self_permissions(
                self.database,
                self.backup_manager,
            )
            if grant.success:
                permission_ready = True
                if grant.injection is None:
                    permission_text = "本软件摄像头和麦克风权限已存在。"
                else:
                    permission_text = (
                        "已写入本软件摄像头和麦克风权限。"
                        "如果当前进程仍无法访问，请重启工具箱。"
                    )
                    self.audit.event(
                        "self_tcc_permission_write",
                        bundle_id=grant.bundle_id,
                        backup_path=grant.backup_path,
                        rows_changed=grant.injection.rows_changed,
                    )
            else:
                injection = grant.injection
                permission_text = (
                    "本软件权限写入验证失败，已自动回滚。"
                    if injection is not None and injection.rolled_back
                    else "本软件权限写入失败。"
                )
                self.audit.event(
                    "self_tcc_permission_write_error",
                    bundle_id=grant.bundle_id,
                    rolled_back=(
                        injection.rolled_back if injection is not None else False
                    ),
                    rollback_error=(
                        injection.rollback_error if injection is not None else None
                    ),
                )
        except Exception as exc:
            permission_text = f"本软件权限写入失败：{exc}"
            self.audit.event(
                "self_tcc_permission_write_error",
                error_type=type(exc).__name__,
                error=str(exc),
            )
        self.refresh_permission_status()
        if permission_text:
            self.permission_status.setText(permission_text)
        if permission_ready:
            return
        if self._permission_prepare:
            return
        self._permission_prepare = True
        self._prepare_camera_done = False
        self._prepare_microphone_done = False
        self._prepare_finishing = False
        timeout = QTimer(self)
        timeout.setSingleShot(True)
        timeout.setInterval(20000)
        timeout.timeout.connect(self._finish_prepare_permissions)
        timeout.start()
        self._prepare_timeout = timeout
        self.start_camera()
        self.start_microphone()
        if self._camera is not None and self._camera.isActive():
            self._mark_prepare_done(camera=True)
        if self._audio_source is not None:
            self._mark_prepare_done(microphone=True)

    def _finish_prepare_permissions(self) -> None:
        self.stop_camera()
        self.stop_microphone()
        timeout = self._prepare_timeout
        if timeout is not None:
            timeout.stop()
            timeout.deleteLater()
        self._prepare_timeout = None
        self._permission_prepare = False
        self._prepare_finishing = False
        self.refresh_permission_status()
        self.environment_changed.emit()

    def _mark_prepare_done(
        self,
        *,
        camera: bool = False,
        microphone: bool = False,
    ) -> None:
        if not self._permission_prepare:
            return
        self._prepare_camera_done = self._prepare_camera_done or camera
        self._prepare_microphone_done = self._prepare_microphone_done or microphone
        if (
            self._prepare_camera_done
            and self._prepare_microphone_done
            and not self._prepare_finishing
        ):
            self._prepare_finishing = True
            QTimer.singleShot(350, self._finish_prepare_permissions)

    def start_camera(self) -> None:
        if self._camera is not None:
            return
        device = QMediaDevices.defaultVideoInput()
        if device.isNull():
            self.camera_status.setText("未检测到摄像头，无法开始测试。")
            self._mark_prepare_done(camera=True)
            return
        self.camera_status.setText("正在请求摄像头权限并启动预览…")
        self.camera_start_button.setEnabled(False)
        self.camera_stop_button.setEnabled(True)
        camera = QCamera(device, self)
        capture = QMediaCaptureSession(self)
        sink = QVideoSink(self)
        capture.setCamera(camera)
        capture.setVideoSink(sink)
        sink.videoFrameChanged.connect(self._camera_frame)
        camera.errorOccurred.connect(self._camera_error)
        camera.activeChanged.connect(self._camera_active_changed)
        self._camera = camera
        self._capture_session = capture
        self._video_sink = sink
        self.audit.event("hardware_test_camera", device=device.description())
        camera.start()

    def _camera_frame(self, frame) -> None:
        image = frame.toImage()
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        self.camera_preview.setPixmap(
            pixmap.scaled(
                self.camera_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _camera_error(self, error, message: str) -> None:
        del error
        self.camera_status.setText(f"摄像头错误：{message}")
        self.stop_camera()
        self._mark_prepare_done(camera=True)

    def _camera_active_changed(self, active: bool) -> None:
        if active:
            self.camera_status.setText("摄像头预览正常，TCC 权限已由系统记录。")
            self.refresh_permission_status()
            self._mark_prepare_done(camera=True)

    def stop_camera(self) -> None:
        camera = self._camera
        if camera is not None:
            camera.stop()
            camera.deleteLater()
        self._camera = None
        self._capture_session = None
        self._video_sink = None
        self.camera_start_button.setEnabled(True)
        self.camera_stop_button.setEnabled(False)
        if self.camera_status.text().startswith("正在"):
            self.camera_status.setText("摄像头测试已停止。")

    def start_microphone(self) -> None:
        if self._audio_source is not None:
            return
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            self.microphone_status.setText("未检测到麦克风，无法开始测试。")
            self._mark_prepare_done(microphone=True)
            return
        audio_format = device.preferredFormat()
        if audio_format.sampleFormat() is QAudioFormat.SampleFormat.Unknown:
            audio_format = QAudioFormat()
            audio_format.setSampleRate(44100)
            audio_format.setChannelCount(1)
            audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        source = QAudioSource(device, audio_format, self)
        source.setBufferSize(max(source.bufferSize(), 4096))
        io_device = source.start()
        if io_device is None or source.error().name != "NoError":
            self.microphone_status.setText(f"无法启动麦克风：{source.error().name}")
            source.deleteLater()
            self._mark_prepare_done(microphone=True)
            return
        self._audio_source = source
        self._audio_device = io_device
        self._audio_sample_format = audio_format.sampleFormat()
        self.microphone_start_button.setEnabled(False)
        self.microphone_stop_button.setEnabled(True)
        self.microphone_status.setText("正在监听麦克风，请说话或拍手。")
        self.audit.event(
            "hardware_test_microphone",
            device=device.description(),
        )
        timer = QTimer(self)
        timer.setInterval(100)
        timer.timeout.connect(self._update_microphone_level)
        timer.start()
        self._audio_level_timer = timer

    def _update_microphone_level(self) -> None:
        if self._audio_device is None:
            return
        data = bytes(self._audio_device.readAll())
        if not data:
            current = max(0, self.microphone_level.value() - 3)
            self._set_microphone_level(current)
            return
        self._mark_prepare_done(microphone=True)
        level = _audio_level(data, self._audio_sample_format)
        self._set_microphone_level(min(100, int(level * 320)))

    def _set_microphone_level(self, value: int) -> None:
        self.microphone_level.setValue(value)
        self.microphone_level.setFormat(f"输入电平 {value}%")

    def stop_microphone(self) -> None:
        timer = self._audio_level_timer
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._audio_level_timer = None
        source = self._audio_source
        if source is not None:
            source.stop()
            source.deleteLater()
        self._audio_source = None
        self._audio_device = None
        self._set_microphone_level(0)
        self.microphone_start_button.setEnabled(True)
        self.microphone_stop_button.setEnabled(False)
        if self.microphone_status.text().startswith("正在"):
            self.microphone_status.setText("麦克风测试已停止。")

    def play_test_tone(self) -> None:
        if self._speaker_sink is not None:
            return
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            self.speaker_status.setText("未检测到扬声器。")
            return
        audio_format = QAudioFormat()
        audio_format.setSampleRate(48000)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(audio_format):
            self.speaker_status.setText("当前扬声器不支持测试音格式。")
            return
        sample_count = int(48000 * 0.8)
        samples = bytearray()
        for index in range(sample_count):
            value = int(0.18 * 32767 * math.sin(2 * math.pi * 440 * index / 48000))
            samples.extend(struct.pack("<h", value))
        buffer = QBuffer(self)
        buffer.setData(QByteArray(bytes(samples)))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        sink = QAudioSink(device, audio_format, self)
        sink.start(buffer)
        self._speaker_sink = sink
        self._speaker_buffer = buffer
        self.speaker_button.setEnabled(False)
        self.speaker_status.setText("正在播放 440 Hz 测试音…")
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(1000)
        timer.timeout.connect(self._finish_test_tone)
        timer.start()
        self._speaker_timer = timer
        self.audit.event("hardware_test_speaker", device=device.description())

    def _finish_test_tone(self) -> None:
        sink = self._speaker_sink
        if sink is None and self._speaker_timer is None:
            return
        if sink is not None:
            sink.stop()
            sink.deleteLater()
        buffer = self._speaker_buffer
        if buffer is not None:
            buffer.close()
            buffer.deleteLater()
        self._speaker_sink = None
        self._speaker_buffer = None
        self._speaker_timer = None
        self.speaker_button.setEnabled(True)
        self.speaker_status.setText("测试音播放完成。")

    def stop_all(self) -> None:
        self.stop_camera()
        self.stop_microphone()
        self._finish_test_tone()
        timeout = self._prepare_timeout
        if timeout is not None:
            timeout.stop()
            timeout.deleteLater()
        self._prepare_timeout = None
        self._permission_prepare = False
        self._prepare_finishing = False


def _audio_level(data: bytes, sample_format: QAudioFormat.SampleFormat) -> float:
    try:
        if sample_format is QAudioFormat.SampleFormat.Int16:
            samples = array("h")
            samples.frombytes(data[: len(data) - len(data) % 2])
            scale = 32768.0
            if sys.byteorder == "big":
                samples.byteswap()
        elif sample_format is QAudioFormat.SampleFormat.Int32:
            samples = array("i")
            samples.frombytes(data[: len(data) - len(data) % 4])
            scale = 2147483648.0
            if sys.byteorder == "big":
                samples.byteswap()
        elif sample_format is QAudioFormat.SampleFormat.Float:
            samples = array("f")
            samples.frombytes(data[: len(data) - len(data) % 4])
            scale = 1.0
            if sys.byteorder == "big":
                samples.byteswap()
        else:
            return 0.0
    except ValueError:
        return 0.0
    recent = samples[-4096:]
    if not recent:
        return 0.0
    mean_square = sum(sample * sample for sample in recent) / len(recent)
    return min(1.0, math.sqrt(mean_square) / scale)
