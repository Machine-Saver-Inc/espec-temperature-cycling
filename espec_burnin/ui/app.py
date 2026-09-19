"""Application entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def _log_path() -> Path:
    folder = Path.home() / ".espec-burn-in"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "espec-burn-in.log"


def main() -> int:
    # Answerable from a command line, which matters when someone is on the
    # phone with a chamber PC that has never seen the internet.
    if any(arg in ("--version", "-V") for arg in sys.argv[1:]):
        from espec_burnin import APP_NAME, __version__

        print(f"{APP_NAME} {__version__}")
        return 0

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(_log_path(), encoding="utf-8"),
                  logging.StreamHandler(sys.stderr)],
    )

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from espec_burnin import APP_NAME
    from espec_burnin.ui.main_window import MainWindow
    from espec_burnin.ui.style import build_stylesheet

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Machine Saver Inc")
    # The window surface stays whatever the machine is set to; only the two
    # colours that have to stay legible against it are chosen here.
    from PySide6.QtGui import QPalette

    dark = app.palette().color(QPalette.Window).lightness() < 128
    app.setStyleSheet(build_stylesheet(dark))

    icon_path = Path(__file__).resolve().parent.parent / "resources" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # One instance only: two copies would fight over the serial port.
    from espec_burnin.ui.single_instance import acquire_lock

    if not acquire_lock():
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(
            None, APP_NAME,
            "Espec Burn-In is already running. Only one copy can use the chamber.",
        )
        return 1

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
