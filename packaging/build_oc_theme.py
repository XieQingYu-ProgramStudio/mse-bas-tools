"""Build the Xie Qingyu Studio OpenCanopy theme resources."""

from __future__ import annotations

import struct
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
    QRadialGradient,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
ICON_SOURCES = (
    ROOT / "packaging/oc_icons",
    ROOT / "tcc_permission_assistant/gui/icons",
)
OUTPUT = ROOT / "oc_theme/XieQingyu/Studio"
LABEL_OUTPUT = ROOT / "oc_theme/Label"
LOGO = ROOT / "tcc_permission_assistant/gui/assets/xieqingyu-studio-logo.png"
_APP = None

NAVY = QColor("#08172C")
NAVY_LIGHT = QColor("#102A4A")
TEAL = QColor("#23B7A9")
BLUE = QColor("#1B70C9")
CYAN = QColor("#78E4E8")
WHITE = QColor("#F5FBFB")
GOLD = QColor("#F4B52D")

PALETTE = {
    0x00: 255,
    0xF6: 238,
    0xF7: 221,
    0x2A: 204,
    0xF8: 187,
    0xF9: 170,
    0x55: 153,
    0xFA: 136,
    0xFB: 119,
    0x80: 102,
    0xFC: 85,
    0xFD: 68,
    0xAB: 51,
    0xFE: 34,
    0xFF: 17,
    0xD6: 0,
}

LABELS = {
    "Apple": "macOS",
    "AppleRecv": "macOS 恢复",
    "AppleTM": "Time Machine",
    "EFIBoot": "EFI",
    "FirmwareSettings": "固件设置",
    "NetworkBoot": "网络启动",
    "Other": "其他系统",
    "ResetNVRAM": "重置 NVRAM",
    "Shell": "命令行",
    "SIPDisabled": "SIP 已关闭",
    "SIPEnabled": "SIP 已启用",
    "Tool": "工具",
    "Windows": "Windows",
}


def main() -> None:
    global _APP
    _APP = QApplication.instance() or QApplication([])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    LABEL_OUTPUT.mkdir(parents=True, exist_ok=True)
    create_background(OUTPUT / "Background.png", OUTPUT / "Background.icns")
    create_icons()
    create_labels()
    (OUTPUT.parent / "README.txt").write_text(
        "谢清宇工作室 OpenCore 主题\n"
        "主题路径：EFI/OC/Resources/Image/XieQingyu/Studio\n"
        "PickerVariant：XieQingyu\\\\Studio\n"
        "由月星BAS工具箱生成。\n",
        encoding="utf-8",
    )
    print(OUTPUT)


def create_background(path: Path, icns_path: Path) -> None:
    width, height = 3840, 2160
    image = QImage(width, height, QImage.Format.Format_RGB32)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor("#061326"))
    gradient.setColorAt(0.55, QColor("#0A213A"))
    gradient.setColorAt(1.0, QColor("#07172A"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(image.rect(), gradient)

    glow = QRadialGradient(QPointF(2950, 650), 1200)
    glow.setColorAt(0.0, QColor(28, 161, 167, 90))
    glow.setColorAt(0.5, QColor(13, 82, 119, 42))
    glow.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.fillRect(image.rect(), glow)

    painter.setPen(QPen(QColor(44, 203, 190, 125), 18))
    painter.drawEllipse(QRectF(-520, -600, 1900, 1900))
    painter.setPen(QPen(QColor(32, 119, 208, 110), 8))
    painter.drawEllipse(QRectF(-760, -460, 2350, 2350))
    painter.setPen(QPen(QColor(88, 226, 226, 55), 3))
    painter.drawArc(QRectF(2100, 80, 1500, 780), 190 * 16, 205 * 16)

    draw_star(painter, QPointF(3230, 380), 56)
    draw_star(painter, QPointF(3000, 620), 24)
    draw_star(painter, QPointF(3450, 760), 14)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 235))
    painter.drawRoundedRect(QRectF(260, 220, 2020, 790), 48, 48)
    logo = QImage(str(LOGO))
    if not logo.isNull():
        target = QRectF(380, 285, 1780, 660)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.drawImage(target, logo)

    tagline_font = QFont("PingFang SC")
    tagline_font.setPixelSize(34)
    tagline_font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(tagline_font)
    painter.setPen(QColor("#8CE3E6"))
    painter.drawText(
        QRectF(292, 1045, 2100, 80),
        "月星BAS工具箱  ·  OPENCORE CUSTOM EDITION",
    )
    badge_font = QFont("PingFang SC")
    badge_font.setPixelSize(26)
    painter.setFont(badge_font)
    painter.setPen(QColor("#B8D7DF"))
    painter.drawText(
        QRectF(2870, 1950, 680, 70),
        Qt.AlignmentFlag.AlignRight,
        "月星BAS · 定制引导",
    )
    painter.end()
    _set_dpi(image)
    if not image.save(str(path), "PNG"):
        raise SystemExit(f"无法写入背景：{path}")
    write_icns(
        icns_path,
        image,
        image.scaled(
            5120,
            2880,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ),
    )


def create_icons() -> None:
    icon_specs = {
        "Apple": ("laptop", None),
        "HardDrive": ("hard-drive", None),
        "OpticalDrive": ("disc", None),
        "AppleRecv": ("rotate-ccw", None),
        "AppleTM": ("clock", None),
        "Other": ("monitor", None),
        "Tool": ("wrench", None),
        "ResetNVRAM": ("refresh-cw", None),
        "Shell": ("terminal", None),
        "FirmwareSettings": ("settings", None),
        "NetworkBoot": ("network", None),
        "Windows": ("windows", None),
    }
    for name, (glyph, _badge) in icon_specs.items():
        image = entry_icon(glyph, None)
        write_icns(
            OUTPUT / f"{name}.icns",
            image.scaled(128, 128),
            image.scaled(256, 256),
        )
        ext_image = entry_icon(glyph, "EXT")
        write_icns(
            OUTPUT / f"Ext{name}.icns",
            ext_image.scaled(128, 128),
            ext_image.scaled(256, 256),
        )

    password = password_image(160, 28)
    write_icns(
        OUTPUT / "Password.icns",
        password,
        password.scaled(320, 56),
    )

    structural = {
        "Selected": (selected_image, (144, 144)),
        "Selector": (selector_image, (40, 40)),
        "BtnFocus": (focus_image, (50, 50)),
        "Cursor": (cursor_image, (24, 24)),
        "Dot": (dot_image, (7, 7)),
        "Enter": (enter_image, (25, 28)),
        "SetDefault": (set_default_image, (40, 40)),
        "Left": (chevron_left_image, (40, 40)),
        "Right": (chevron_right_image, (40, 40)),
        "Lock": (lock_image, (80, 111)),
        "Restart": (restart_action_image, (36, 36)),
        "ShutDown": (shutdown_action_image, (36, 36)),
    }
    for name, (factory, dimensions) in structural.items():
        width, height = dimensions
        image1 = factory(width, height)
        image2 = factory(width * 2, height * 2)
        write_icns(OUTPUT / f"{name}.icns", image1, image2)


def entry_icon(glyph: str, badge: str | None) -> QImage:
    image = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    tile = QRectF(18, 18, 220, 220)
    gradient = QLinearGradient(tile.topLeft(), tile.bottomRight())
    gradient.setColorAt(0.0, QColor("#12345A"))
    gradient.setColorAt(1.0, QColor("#081A31"))
    painter.setPen(QPen(QColor("#4ACFC3"), 3))
    painter.setBrush(gradient)
    painter.drawRoundedRect(tile, 48, 48)
    painter.setPen(QPen(QColor(70, 210, 212, 65), 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(34, 34, 188, 188))
    if glyph == "windows":
        draw_windows(painter)
    else:
        render_glyph(painter, glyph, QRectF(66, 66, 124, 124), WHITE)
    if badge:
        badge_font = QFont("Avenir Next")
        badge_font.setPixelSize(21)
        badge_font.setWeight(QFont.Weight.Bold)
        painter.setFont(badge_font)
        badge_rect = QRectF(149, 167, 60, 40)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(19, 106, 122, 230))
        painter.drawRoundedRect(badge_rect, 12, 12)
        painter.setPen(CYAN)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge)
    painter.end()
    return image


def selected_image(width: int, height: int) -> QImage:
    image = transparent(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = width / 144
    painter.setPen(QPen(CYAN, 8 * scale))
    painter.setBrush(QColor(29, 117, 133, 105))
    painter.drawRoundedRect(
        QRectF(18 * scale, 18 * scale, 252 * scale, 252 * scale),
        50 * scale,
        50 * scale,
    )
    painter.end()
    return image


def selector_image(width: int, height: int) -> QImage:
    image = transparent(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = width / 40
    painter.setPen(QPen(QColor(101, 230, 235, 190), 5 * scale))
    painter.setBrush(QColor(20, 110, 128, 32))
    painter.drawEllipse(QRectF(6 * scale, 6 * scale, 68 * scale, 68 * scale))
    painter.end()
    return image


def focus_image(width: int, height: int) -> QImage:
    image = transparent(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = width / 50
    painter.setPen(QPen(QColor("#7DE2E7"), 6 * scale))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(
        QRectF(7 * scale, 7 * scale, 86 * scale, 86 * scale),
        18 * scale,
        18 * scale,
    )
    painter.end()
    return image


def cursor_image(width: int, height: int) -> QImage:
    image = transparent(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    render_glyph(
        painter,
        "mouse-pointer-2",
        QRectF(1, 1, width - 2, height - 2),
        CYAN,
    )
    painter.end()
    return image


def dot_image(width: int, height: int) -> QImage:
    image = transparent(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(CYAN)
    painter.drawEllipse(QRectF(1, 1, width - 2, height - 2))
    painter.end()
    return image


def enter_image(width: int, height: int) -> QImage:
    image = transparent(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#4ACFC3"), max(1, width // 12)))
    painter.setBrush(QColor("#0B3550"))
    painter.drawRoundedRect(QRectF(1, 1, width - 2, height - 2), 5, 5)
    render_glyph(
        painter,
        "corner-down-left",
        QRectF(width * 0.25, 4, height - 8, height - 8),
        WHITE,
    )
    painter.end()
    return image


def set_default_image(width: int, height: int) -> QImage:
    image = transparent(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(CYAN, max(1, width // 10)))
    painter.setBrush(QColor(12, 48, 77, 210))
    painter.drawEllipse(QRectF(2, 2, width - 4, height - 4))
    render_glyph(
        painter,
        "check",
        QRectF(width * 0.25, height * 0.25, width * 0.5, height * 0.5),
        WHITE,
    )
    painter.end()
    return image


def chevron_left_image(width: int, height: int) -> QImage:
    image = transparent(width, height)
    painter = QPainter(image)
    render_glyph(
        painter,
        "chevron-left",
        QRectF(6, 5, width - 12, height - 10),
        CYAN,
    )
    painter.end()
    return image


def chevron_right_image(width: int, height: int) -> QImage:
    image = transparent(width, height)
    painter = QPainter(image)
    render_glyph(
        painter,
        "chevron-right",
        QRectF(6, 5, width - 12, height - 10),
        CYAN,
    )
    painter.end()
    return image


def lock_image(width: int, height: int) -> QImage:
    image = transparent(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(10, 31, 55, 240))
    painter.drawRoundedRect(QRectF(8, 8, width - 16, height - 16), 32, 32)
    render_glyph(
        painter, "lock", QRectF(width * 0.22, 20, width * 0.56, height * 0.48), CYAN
    )
    painter.end()
    return image


def restart_action_image(width: int, height: int) -> QImage:
    return action_image(width, height, "rotate-cw")


def shutdown_action_image(width: int, height: int) -> QImage:
    return action_image(width, height, "power")


def action_image(width: int, height: int, glyph: str) -> QImage:
    image = transparent(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#4ACFC3"), max(1, width // 12)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(2, 2, width - 4, height - 4))
    render_glyph(
        painter,
        glyph,
        QRectF(width * 0.2, height * 0.2, width * 0.6, height * 0.6),
        WHITE,
    )
    painter.end()
    return image


def password_image(width: int, height: int) -> QImage:
    image = transparent(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#4ACFC3"), 2))
    painter.setBrush(QColor(10, 31, 55, 245))
    painter.drawRoundedRect(QRectF(1, 1, width - 2, height - 2), 5, 5)
    render_glyph(
        painter,
        "key-round",
        QRectF(6, 5, height - 10, height - 10),
        CYAN,
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(WHITE)
    dot_y = height // 2 - 2
    for index in range(6):
        painter.drawEllipse(QRectF(44 + index * 16, dot_y, 4, 4))
    painter.end()
    return image


def draw_windows(painter: QPainter) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#F4FBFB"))
    cell = 48
    gap = 10
    start_x = 76
    start_y = 78
    for row in range(2):
        for column in range(2):
            painter.drawRoundedRect(
                QRectF(
                    start_x + column * (cell + gap),
                    start_y + row * (cell + gap),
                    cell,
                    cell,
                ),
                6,
                6,
            )


def create_labels() -> None:
    for name, text in LABELS.items():
        for scale, suffix in ((1, ".lbl"), (2, ".l2x")):
            (LABEL_OUTPUT / f"{name}{suffix}").write_bytes(render_label(text, scale))


def render_label(text: str, scale: int) -> bytes:
    height = 12 * scale
    font = QFont("PingFang SC")
    font.setPixelSize(10 * scale)
    font.setWeight(QFont.Weight.DemiBold)
    metrics = QFontMetrics(font)
    width = metrics.horizontalAdvance(text) + 4 * scale
    width = min(width, 340 * scale)
    image = QImage(
        width,
        height,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setFont(font)
    painter.setPen(WHITE)
    painter.drawText(
        QRectF(2 * scale, 0, width - 4 * scale, height),
        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
        text,
    )
    painter.end()
    inverse = {255 - value: key for key, value in PALETTE.items()}
    alpha_values = sorted(inverse)
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            alpha = image.pixelColor(x, y).alpha()
            nearest = min(alpha_values, key=lambda value: abs(value - alpha))
            pixels.append(inverse[nearest])
    return struct.pack(">BHH", 1, width, height) + bytes(pixels)


def render_glyph(
    painter: QPainter,
    name: str,
    rect: QRectF,
    color: QColor,
) -> None:
    path = next(
        (
            directory / f"{name}.svg"
            for directory in ICON_SOURCES
            if (directory / f"{name}.svg").is_file()
        ),
        None,
    )
    if path is None:
        return
    svg = path.read_text(encoding="utf-8")
    svg = svg.replace("currentColor", color.name())
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    renderer.render(painter, rect)


def draw_star(painter: QPainter, center: QPointF, radius: float) -> None:
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(GOLD)
    painter.translate(center)
    points = [
        QPointF(0, -radius),
        QPointF(radius * 0.22, -radius * 0.22),
        QPointF(radius, 0),
        QPointF(radius * 0.22, radius * 0.22),
        QPointF(0, radius),
        QPointF(-radius * 0.22, radius * 0.22),
        QPointF(-radius, 0),
        QPointF(-radius * 0.22, -radius * 0.22),
    ]
    painter.drawPolygon(points)
    painter.restore()


def transparent(width: int, height: int | None = None) -> QImage:
    image = QImage(
        width,
        height or width,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.fill(Qt.GlobalColor.transparent)
    return image


def write_icns(path: Path, image1: QImage, image2: QImage) -> None:
    _set_dpi(image1)
    _set_dpi(image2)
    records = (
        (b"ic07", _png_bytes(image1)),
        (b"ic13", _png_bytes(image2)),
    )
    payload = bytearray()
    for record_type, png_data in records:
        payload.extend(record_type)
        payload.extend(struct.pack(">I", len(png_data) + 8))
        payload.extend(png_data)
    path.write_bytes(b"icns" + struct.pack(">I", len(payload) + 8) + payload)


def _png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def _set_dpi(image: QImage) -> None:
    dots_per_meter = round(144 / 0.0254)
    image.setDotsPerMeterX(dots_per_meter)
    image.setDotsPerMeterY(dots_per_meter)


if __name__ == "__main__":
    main()
