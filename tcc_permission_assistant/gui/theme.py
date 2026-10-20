"""Application palette and Qt stylesheet."""

from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

COLORS = {
    "ink": "#20262D",
    "muted": "#64717C",
    "faint": "#8A959E",
    "canvas": "#F2F5F6",
    "surface": "#FFFFFF",
    "surface_alt": "#E9EEF0",
    "line": "#D8E0E3",
    "accent": "#146A7A",
    "accent_hover": "#105B69",
    "accent_soft": "#DDEFF2",
    "success": "#217553",
    "success_soft": "#DFF2E8",
    "warning": "#9A5B13",
    "warning_soft": "#F8EBD8",
    "danger": "#B42318",
    "danger_hover": "#941D14",
    "danger_soft": "#FBE5E2",
    "sidebar": "#172027",
    "sidebar_muted": "#A9B6BE",
    "sidebar_active": "#23343D",
}


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(QFont("PingFang SC", 13))

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["canvas"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["ink"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["surface_alt"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["ink"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["ink"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)


STYLESHEET = f"""
QWidget {{
    color: {COLORS["ink"]};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background: {COLORS["canvas"]};
}}
QDialog#aboutDialog {{
    background: #FFFFFF;
}}
QFrame#aboutDivider {{
    background: #E2E8EA;
    border: none;
    max-height: 1px;
}}
QLabel#aboutProduct {{
    color: {COLORS["ink"]};
    font-size: 27px;
    font-weight: 700;
}}
QLabel#aboutDeveloper {{
    color: {COLORS["ink"]};
    font-size: 14px;
    font-weight: 600;
}}
QFrame#splashFrame {{
    background: #FFFFFF;
    border: 1px solid #C9D5D9;
    border-radius: 14px;
}}
QLabel#splashTitle {{
    color: #172027;
    font-size: 22px;
    font-weight: 700;
}}
QLabel#splashCaption {{
    color: {COLORS["muted"]};
    font-size: 12px;
}}
QLabel#splashStatus {{
    color: {COLORS["muted"]};
    font-size: 11px;
}}
QFrame#splashIconTile {{
    background: {COLORS["accent_soft"]};
    border: 1px solid #B8DDE3;
    border-radius: 13px;
}}
QProgressBar#splashProgress {{
    background: #E5ECEE;
    border: none;
    border-radius: 2px;
    max-height: 4px;
}}
QProgressBar#splashProgress::chunk {{
    background: {COLORS["accent"]};
    border-radius: 2px;
}}
QProgressBar#levelMeter {{
    background: #E5ECEE;
    border: 1px solid {COLORS["line"]};
    border-radius: 5px;
    min-height: 22px;
    text-align: center;
    color: {COLORS["ink"]};
    font-size: 11px;
    font-weight: 600;
}}
QProgressBar#levelMeter::chunk {{
    background: {COLORS["success"]};
    border-radius: 4px;
}}
QWidget#contentRoot {{
    background: {COLORS["canvas"]};
}}
QFrame#sidebar {{
    background: {COLORS["sidebar"]};
    border: none;
}}
QLabel#brandTitle {{
    color: #FFFFFF;
    font-size: 15px;
    font-weight: 700;
}}
QLabel#brandCaption {{
    color: {COLORS["sidebar_muted"]};
    font-size: 11px;
}}
QLabel#sidebarCaption {{
    color: {COLORS["sidebar_muted"]};
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#navButton {{
    color: {COLORS["sidebar_muted"]};
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 16px;
    text-align: left;
    font-weight: 600;
}}
QPushButton#navButton[nested="true"] {{
    padding-left: 26px;
}}
QPushButton#navButton:hover {{
    color: #FFFFFF;
    background: #202E36;
}}
QPushButton#navButton:checked {{
    color: #FFFFFF;
    background: {COLORS["sidebar_active"]};
    border-left: 3px solid #6DC4CF;
    padding-left: 9px;
}}
QPushButton#navButton[nested="true"]:checked {{
    padding-left: 23px;
}}
QPushButton#moduleButton {{
    color: #DCE5E8;
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px 4px;
    min-height: 16px;
    text-align: left;
    font-size: 12px;
    font-weight: 700;
}}
QPushButton#moduleButton:hover {{
    background: #202E36;
}}
QPushButton#disclosure {{
    background: transparent;
    border: none;
    padding: 4px;
    min-height: 18px;
    min-width: 18px;
}}
QPushButton#disclosure:hover {{
    background: #25343C;
}}
QLabel#pageTitle {{
    font-size: 25px;
    font-weight: 700;
    color: {COLORS["ink"]};
}}
QLabel#pageSubtitle {{
    color: {COLORS["muted"]};
    font-size: 12px;
}}
QLabel#sectionTitle {{
    font-size: 14px;
    font-weight: 700;
}}
QLabel#muted {{
    color: {COLORS["muted"]};
}}
QLabel#value {{
    color: {COLORS["ink"]};
    font-weight: 600;
}}
QLabel#mono {{
    font-family: "SF Mono", "Menlo", monospace;
    font-size: 12px;
}}
QFrame#panel {{
    background: {COLORS["surface"]};
    border: 1px solid {COLORS["line"]};
    border-radius: 7px;
}}
QFrame#dropZone {{
    background: {COLORS["surface"]};
    border: 1px dashed #A7B5BB;
    border-radius: 7px;
}}
QFrame#warningBox {{
    background: {COLORS["warning_soft"]};
    border: 1px solid #E7C89C;
    border-radius: 6px;
}}
QFrame#successBox {{
    background: {COLORS["success_soft"]};
    border: 1px solid #B7DCC8;
    border-radius: 6px;
}}
QFrame#statusBar {{
    background: #E8EDEF;
    border-top: 1px solid {COLORS["line"]};
}}
QStatusBar {{
    background: #E8EDEF;
    border-top: 1px solid {COLORS["line"]};
}}
QStatusBar::item {{
    border: none;
}}
QPushButton {{
    background: {COLORS["surface"]};
    border: 1px solid #C9D3D7;
    border-radius: 6px;
    padding: 7px 13px;
    min-height: 20px;
}}
QPushButton:hover {{
    background: #F7F9FA;
    border-color: #AEBCC2;
}}
QPushButton:pressed {{
    background: {COLORS["surface_alt"]};
}}
QPushButton:disabled {{
    color: #9AA4AA;
    background: #EEF1F2;
    border-color: #DCE2E4;
}}
QPushButton#primary {{
    color: #FFFFFF;
    background: {COLORS["accent"]};
    border-color: {COLORS["accent"]};
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: {COLORS["accent_hover"]};
    border-color: {COLORS["accent_hover"]};
}}
QPushButton#danger {{
    color: #FFFFFF;
    background: {COLORS["danger"]};
    border-color: {COLORS["danger"]};
    font-weight: 600;
}}
QPushButton#danger:hover {{
    background: {COLORS["danger_hover"]};
    border-color: {COLORS["danger_hover"]};
}}
QPushButton#primary:disabled, QPushButton#danger:disabled {{
    color: #8C989E;
    background: #E4E9EB;
    border-color: #D4DCDF;
}}
QPushButton#quiet {{
    background: transparent;
    border-color: transparent;
    color: {COLORS["muted"]};
}}
QPushButton#quiet:hover {{
    background: {COLORS["surface_alt"]};
    color: {COLORS["ink"]};
}}
QPushButton#sidebarAboutButton {{
    color: {COLORS["sidebar_muted"]};
    background: transparent;
    border: none;
    text-align: left;
    padding: 7px 8px;
    font-size: 11px;
}}
QPushButton#sidebarAboutButton:hover {{
    color: #FFFFFF;
    background: #202E36;
}}
QLineEdit, QComboBox, QPlainTextEdit, QTextEdit, QTextBrowser, QSpinBox {{
    background: {COLORS["surface"]};
    border: 1px solid #C9D3D7;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {COLORS["accent"]};
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {COLORS["accent"]};
}}
QComboBox {{
    padding-right: 24px;
}}
QComboBox QAbstractItemView {{
    background: {COLORS["surface"]};
    border: 1px solid {COLORS["line"]};
    selection-background-color: {COLORS["accent_soft"]};
    selection-color: {COLORS["ink"]};
}}
QTableWidget, QTableView {{
    background: {COLORS["surface"]};
    alternate-background-color: #F7F9FA;
    border: 1px solid {COLORS["line"]};
    border-radius: 6px;
    gridline-color: #E5EAEC;
    selection-background-color: {COLORS["accent_soft"]};
    selection-color: {COLORS["ink"]};
}}
QHeaderView::section {{
    background: #EEF2F3;
    color: {COLORS["muted"]};
    border: none;
    border-bottom: 1px solid {COLORS["line"]};
    border-right: 1px solid #E2E7E9;
    padding: 7px 8px;
    font-size: 11px;
    font-weight: 700;
}}
QTableCornerButton::section {{
    background: #EEF2F3;
    border: none;
}}
QListWidget#appList {{
    background: transparent;
    border: none;
    outline: 0;
}}
QListWidget#appList::item {{
    color: {COLORS["ink"]};
    background: transparent;
    border-radius: 5px;
    padding: 8px 9px;
}}
QListWidget#appList::item:hover {{
    background: {COLORS["surface_alt"]};
}}
QListWidget#appList::item:selected {{
    color: {COLORS["accent"]};
    background: {COLORS["accent_soft"]};
}}
QCheckBox {{
    spacing: 7px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #AAB7BD;
    border-radius: 3px;
    background: #FFFFFF;
}}
QCheckBox::indicator:checked {{
    background: {COLORS["accent"]};
    border-color: {COLORS["accent"]};
}}
QLabel[badge="allowed"] {{
    color: {COLORS["success"]};
    background: {COLORS["success_soft"]};
    border: 1px solid #B7DCC8;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel[badge="denied"] {{
    color: {COLORS["danger"]};
    background: {COLORS["danger_soft"]};
    border: 1px solid #E8C2BE;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel[badge="unknown"] {{
    color: {COLORS["warning"]};
    background: {COLORS["warning_soft"]};
    border: 1px solid #E7C89C;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel[badge="none"] {{
    color: {COLORS["muted"]};
    background: #EEF2F3;
    border: 1px solid #D9E0E3;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel[badge="accent"] {{
    color: {COLORS["accent"]};
    background: {COLORS["accent_soft"]};
    border: 1px solid #B8DDE3;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}}
QSplitter::handle {{
    background: {COLORS["line"]};
    height: 1px;
}}
QSplitter::handle:horizontal {{
    background: transparent;
    width: 8px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #C5D0D4;
    min-height: 28px;
    border-radius: 4px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QToolTip {{
    color: #FFFFFF;
    background: #26343C;
    border: none;
    padding: 5px;
}}
"""
