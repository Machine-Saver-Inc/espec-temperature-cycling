#!/usr/bin/env python3
"""Regenerate the README screenshots.

Qt renders offscreen, so this produces identical images on any machine with no
display and no chamber attached. Run it before every release:

    python tools/screenshots.py

Images land in docs/images/ and are committed. Look at them afterwards --
clipped text, overlapping widgets and a plot that ignores the theme are all
things only a human eye catches.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "images"

WIDTH, HEIGHT = 980, 720


@dataclass(frozen=True)
class FakePort:
    """A stand-in so the screenshots do not depend on what is plugged in."""

    device: str
    description: str
    serial_number: str | None = None
    vid: int | None = 0x0403
    pid: int | None = 0x6001

    @property
    def is_known_usb_serial(self) -> bool:
        return True

    @property
    def is_probably_bluetooth(self) -> bool:
        return "bluetooth" in self.description.lower()

    @property
    def label(self) -> str:
        return f"{self.device} — {self.description}"


FAKE_PORTS = [
    FakePort("COM3", "USB Serial Port (FTDI FT232R)", "AB0KX1QZ"),
    FakePort("COM1", "Communications Port"),
    FakePort("COM7", "Standard Serial over Bluetooth link", None, None, None),
]


def shoot(widget, name: str, *, width: int = WIDTH, height: int = HEIGHT) -> None:
    from PySide6.QtWidgets import QApplication

    widget.resize(width, height)
    widget.show()
    QApplication.processEvents()
    QApplication.processEvents()
    path = OUT / f"{name}.png"
    widget.grab().save(str(path))
    print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size // 1024} KB)")


def main() -> int:
    from unittest import mock

    from PySide6.QtWidgets import QApplication

    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication([])

    from espec_burnin import __version__
    from espec_burnin.ui.style import STYLESHEET

    app.setStyleSheet(STYLESHEET)

    from espec_burnin.core.capability import ChamberProfile, bin_for
    from espec_burnin.core.profile import Recipe, setpoint_at
    from espec_burnin.core.run_controller import RunState, RunTuning, Status
    from espec_burnin.hardware.errors import PortBusyError
    from espec_burnin.hardware.f4 import ConnectionSettings
    from espec_burnin.ui.capability_page import CapabilityPage
    from espec_burnin.ui.pages import ConnectPage, RecipePage
    from espec_burnin.ui.run_page import RunPage
    from espec_burnin.ui.settings_page import SettingsPage

    tmp = Path(tempfile.mkdtemp())
    print("Rendering:")

    with mock.patch("espec_burnin.hardware.ports.list_serial_ports",
                    return_value=FAKE_PORTS), \
         mock.patch("espec_burnin.core.capability.profiles_dir",
                    return_value=tmp / "profiles"), \
         mock.patch("espec_burnin.core.chambers.chambers_path",
                    return_value=tmp / "chambers.json"), \
         mock.patch("espec_burnin.core.recorder.results_root",
                    return_value=tmp / "results"), \
         mock.patch("espec_burnin.ui.settings.settings_path",
                    return_value=tmp / "settings.json"):

        # The whole window, so the footer's Report a problem button shows.
        from espec_burnin.ui.main_window import MainWindow

        window = MainWindow()
        window.home.set_connection(
            "Chamber connected on COM3 — currently 23.6 °C.", True
        )
        window.home.set_version_line(__version__, "18 Sep 2026 14:02")
        shoot(window, "home")

        connect = ConnectPage(ConnectionSettings())
        connect.refresh()
        connect.result.setText(
            "Connected on COM3. Chamber is at 23.6 °C."
        )
        connect.result.setObjectName("StatusGood")
        connect.result.style().polish(connect.result)
        shoot(connect, "connect")

        recipe = RecipePage(Recipe(), "L. Bach")
        recipe.batch.setText("MS-4412")
        shoot(recipe, "recipe", height=820)

        run = RunPage()
        run.begin("MS-4412", "COM3", 12)
        for seconds in range(0, 12600, 300):
            point = setpoint_at(Recipe(), seconds)
            run.update_status(Status(RunState.RUNNING, point, point.setpoint_c - 1.1,
                                     seconds, 48 * 3600 - seconds, True, ""))
        shoot(run, "running")

        point = setpoint_at(Recipe(), 12600)
        run.update_status(Status(
            RunState.COMMS_LOST, point, None, 12600, 1, False, "",
            error=PortBusyError(port="COM3", holders=("TeraTerm.exe (pid 4412)",)),
        ))
        shoot(run, "port-in-use")

        shoot(SettingsPage(ConnectionSettings(), RunTuning()), "settings", height=880)

        # A representative measured profile: fast near ambient, slow at the ends.
        cooling = {str(bin_for(t)): r for t, r in
                   [(75, 2.8), (65, 2.7), (55, 2.5), (45, 2.3), (35, 2.0),
                    (25, 1.7), (15, 1.4), (5, 1.1), (-5, 0.7), (-15, 0.3)]}
        heating = {str(bin_for(t)): r for t, r in
                   [(-15, 3.2), (-5, 3.2), (5, 3.0), (15, 3.0), (25, 2.9),
                    (35, 2.7), (45, 2.5), (55, 2.2), (65, 1.8), (75, 1.2)]}
        capability = CapabilityPage()
        capability.show_result(ChamberProfile(
            chamber_model="Espec BTZ-133", chamber_serial="0612223",
            name="Loaded — 12 boards, 2 cables through the left port",
            loaded=True, cooling_rates=cooling, heating_rates=heating,
            reachable_min_c=-17.5, reachable_max_c=82.0,
        ))
        shoot(capability, "capability")

        # The setup screen: the chamber is the identity, tests hang under it.
        from espec_burnin.core.capability import save_profile
        from espec_burnin.core.chambers import Chamber, save_chamber

        save_chamber(Chamber(model="Espec BTZ-133", serial="0612223",
                             adapter_serial="AB0KX1QZ"))
        for test_name, is_loaded in [("Loaded \u2014 12 boards", True),
                                     ("Empty, ports closed", False)]:
            save_profile(ChamberProfile(
                chamber_model="Espec BTZ-133", chamber_serial="0612223",
                name=test_name, loaded=is_loaded,
                reachable_min_c=-17.5, reachable_max_c=82.0))
        setup = CapabilityPage()
        setup.set_chamber(Chamber(model="Espec BTZ-133", serial="0612223",
                                  adapter_serial="AB0KX1QZ"))
        shoot(setup, "chamber-setup", height=1040)

        # Reporting a problem, with the program's state already filled in.
        from espec_burnin.ui.report_dialog import ReportDialog

        dialog = ReportDialog({
            "Screen open": "Running a burn-in",
            "Chamber": "Espec BTZ-133 — Serial 0612223",
            "Port": "COM3",
            "Adapter": "USB Serial Port (FTDI FT232R)",
            "Controller settings": "address 201, 19200 baud, 8N1, timeout 0.35s, "
                                   "3 retries, write function 16",
            "Safety limits": "-25 to 85 °C",
            "Run in progress": "yes",
            "Batch": "MS-4412",
            "Recipe": "12 cycles, -20 to 80 °C, cool 60 min / heat 60 min",
            "Last sample": "cycle 3, ramp_down, setpoint -8 °C, measured -6.2 °C",
        })
        dialog.summary.setText("Chamber stalls before reaching -20 °C")
        dialog.description.setPlainText(
            "Cools briskly to about 0 °C, then slows and stops around -17.5 °C.")
        shoot(dialog, "report", width=680, height=800)

    print(f"\nDone. {len(list(OUT.glob('*.png')))} images in {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
