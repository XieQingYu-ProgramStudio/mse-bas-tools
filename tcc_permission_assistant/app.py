"""PyQt6 desktop application entry point."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PyQt6.QtWidgets import QApplication

from tcc_permission_assistant import __version__
from tcc_permission_assistant.branding import APP_NAME, APP_SHORT_NAME
from tcc_permission_assistant.core.logger import configure_logging
from tcc_permission_assistant.core.settings import AppSettings
from tcc_permission_assistant.gui.splash import StartupController
from tcc_permission_assistant.gui.theme import apply_theme


def main(argv: Sequence[str] | None = None) -> int:
    app = QApplication.instance()
    if app is None:
        app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_SHORT_NAME)
    app.setQuitOnLastWindowClosed(True)
    apply_theme(app)
    audit = configure_logging()
    settings = AppSettings()
    startup = StartupController(app, audit, settings=settings)
    startup.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
