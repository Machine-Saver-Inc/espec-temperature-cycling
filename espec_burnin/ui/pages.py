"""The screens. One obvious action on each."""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from espec_burnin.core.capability import (
    ChamberProfile,
    best_profile_for,
    load_profiles,
)
from espec_burnin.core.profile import Recipe, format_duration
from espec_burnin.hardware import ports as ports_mod
from espec_burnin.hardware.errors import ChamberError
from espec_burnin.hardware.f4 import ConnectionSettings
from espec_burnin.ui.widgets import (
    check,
    field_row,
    int_spin,
    primary,
    spin,
    subtitle,
    title,
)


class ProbeWorker(QThread):
    """Port probing off the GUI thread, so a dead port never freezes the window."""

    found = Signal(object, float)
    not_found = Signal(object)          # ChamberError or None

    def __init__(self, settings: ConnectionSettings, device: str | None = None) -> None:
        super().__init__()
        self.device = device
        self.settings = settings

    def run(self) -> None:
        if self.device:
            temperature, error = ports_mod.probe_port(self.device, self.settings)
            if temperature is None:
                self.not_found.emit(error)
                return
            match = next(
                (p for p in ports_mod.list_serial_ports() if p.device == self.device),
                None,
            )
            self.found.emit(match, temperature)
            return

        port, temperature, error = ports_mod.autodetect(self.settings)
        if port is None:
            self.not_found.emit(error)
        else:
            self.found.emit(port, temperature)


class HomePage(QWidget):
    start_requested = Signal()
    results_requested = Signal()
    settings_requested = Signal()
    capability_requested = Signal()
    check_now_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(14)
        layout.addStretch(1)
        layout.addWidget(title("Espec Burn-In"))
        layout.addWidget(
            subtitle("Temperature cycling for PCB burn-in.")
        )
        layout.addSpacing(24)

        start = primary("Start a burn-in run")
        start.clicked.connect(self.start_requested)
        layout.addWidget(start, alignment=Qt.AlignLeft)

        results = QPushButton("Open past results")
        results.clicked.connect(self.results_requested)
        layout.addWidget(results, alignment=Qt.AlignLeft)

        capability = QPushButton("Measure the chamber's speed")
        capability.clicked.connect(self.capability_requested)
        layout.addWidget(capability, alignment=Qt.AlignLeft)

        settings = QPushButton("Settings")
        settings.clicked.connect(self.settings_requested)
        layout.addWidget(settings, alignment=Qt.AlignLeft)

        layout.addStretch(2)
        self.status = QLabel("")
        self.status.setObjectName("StatusGood")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        # The installed version, readable without digging into the title bar --
        # a chamber PC with no internet will never be told about an update, so
        # somebody has to be able to read this out over the phone.
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 8, 0, 0)
        self.version_label = QLabel("")
        self.version_label.setObjectName("Hint")
        footer.addWidget(self.version_label)
        footer.addSpacing(10)
        self.check_now = QPushButton("Check for updates")
        self.check_now.setFlat(True)
        self.check_now.clicked.connect(self.check_now_requested)
        footer.addWidget(self.check_now)
        footer.addStretch(1)
        layout.addLayout(footer)

    def set_version_line(self, version: str, last_checked: str | None,
                         failed: bool = False) -> None:
        if failed:
            when = " \u00b7 could not reach GitHub to check"
        elif last_checked:
            when = f" \u00b7 last checked {last_checked}"
        else:
            when = " \u00b7 not checked yet"
        self.version_label.setText(f"Version {version}{when}")
        self.version_label.setObjectName("StatusWarn" if failed else "Hint")
        self.version_label.style().polish(self.version_label)

    def set_connection(self, text: str, ok: bool) -> None:
        self.status.setText(text)
        self.status.setObjectName("StatusGood" if ok else "StatusWarn")
        self.status.style().polish(self.status)


class ConnectPage(QWidget):
    """Port selection, auto-detect, and guidance when it does not work."""

    connected = Signal(object)
    back = Signal()

    def __init__(self, settings: ConnectionSettings) -> None:
        super().__init__()
        self._worker: ProbeWorker | None = None
        self._ports: list = []
        self.settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 40, 48, 40)
        layout.setSpacing(12)
        layout.addWidget(title("Connect to the chamber"))
        self.hint = subtitle(
            "Pick the port the chamber is plugged into, then press Test connection."
        )
        layout.addWidget(self.hint)

        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.list, 1)

        self.no_ports = QLabel(self._no_ports_help())
        self.no_ports.setWordWrap(True)
        self.no_ports.setTextFormat(Qt.RichText)
        self.no_ports.hide()
        layout.addWidget(self.no_ports, 1)

        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.RichText)
        layout.addWidget(self.result)

        buttons = QHBoxLayout()
        self.test = primary("Test connection")
        self.test.clicked.connect(self._test_selected)
        self.test.setEnabled(False)
        buttons.addWidget(self.test)

        self.autodetect = QPushButton("Find it for me")
        self.autodetect.clicked.connect(self._autodetect)
        buttons.addWidget(self.autodetect)

        self.refresh_button = QPushButton("Check again")
        self.refresh_button.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_button)

        buttons.addStretch(1)
        back = QPushButton("Back")
        back.clicked.connect(self.back)
        buttons.addWidget(back)
        layout.addLayout(buttons)

        # Plugging the adapter in while this screen is open makes it appear.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)
        self.refresh()

    @staticmethod
    def _no_ports_help() -> str:
        dialout = ports_mod.linux_dialout_hint()
        extra = (
            f"<li>If the port exists but cannot be opened, add your user to the "
            f"<code>dialout</code> group:<br><code>{dialout}</code></li>"
            if dialout
            else ""
        )
        return (
            "<b>No serial ports found on this computer.</b>"
            "<ol>"
            "<li>Check the USB-to-serial adapter is plugged into this computer.</li>"
            "<li>Check the serial cable runs from that adapter to the communications "
            "port on the chamber.</li>"
            "<li>On Windows, open Device Manager and look under "
            "<i>Ports (COM &amp; LPT)</i>. A yellow warning triangle, or the adapter "
            "listed under <i>Other devices</i>, means the driver is not installed — "
            "install the driver for your adapter brand (FTDI, Prolific, Silicon Labs "
            "or CH340).</li>"
            "<li>On Linux, run <code>ls /dev/ttyUSB* /dev/ttyACM*</code>. If nothing is "
            "listed the adapter is not being detected; <code>dmesg | tail</code> right "
            "after plugging it in will say why.</li>"
            f"{extra}"
            "</ol>"
        )

    def refresh(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        ports = ports_mod.list_serial_ports()
        if [p.device for p in ports] == [p.device for p in self._ports]:
            return
        self._ports = ports

        self.list.clear()
        for port in ports:
            item = QListWidgetItem(port.label)
            item.setData(Qt.UserRole, port)
            self.list.addItem(item)

        has_ports = bool(ports)
        self.list.setVisible(has_ports)
        self.no_ports.setVisible(not has_ports)
        self.autodetect.setEnabled(has_ports)
        self.hint.setVisible(has_ports)
        if has_ports and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)

    def _selection_changed(self) -> None:
        self.test.setEnabled(self.list.currentItem() is not None)

    def _selected_port(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _busy(self, busy: bool, message: str = "") -> None:
        self.test.setEnabled(not busy and self.list.currentItem() is not None)
        self.autodetect.setEnabled(not busy and bool(self._ports))
        if message:
            self.result.setText(message)
            self.result.setObjectName("")
            self.result.style().polish(self.result)

    def _test_selected(self) -> None:
        port = self._selected_port()
        if port is None:
            return
        self._busy(True, f"Testing {port.device}…")
        self._start_worker(ProbeWorker(self.settings, port.device))

    def _autodetect(self) -> None:
        self._busy(True, "Looking for the chamber on each port…")
        self._start_worker(ProbeWorker(self.settings, None))

    def _start_worker(self, worker: ProbeWorker) -> None:
        self._worker = worker
        worker.found.connect(self._on_found)
        worker.not_found.connect(self._on_not_found)
        worker.finished.connect(lambda: self._busy(False))
        worker.start()

    def _on_found(self, port, temperature: float) -> None:
        self.result.setText(
            f"Connected on {port.device}. Chamber is at {temperature:.1f} °C."
        )
        self.result.setObjectName("StatusGood")
        self.result.style().polish(self.result)
        self.connected.emit(port)

    def _on_not_found(self, error) -> None:
        self.result.setText(describe_error(error))
        self.result.setObjectName("StatusBad")
        self.result.style().polish(self.result)


def describe_error(error: ChamberError | None) -> str:
    """Rich-text explanation of a connection failure, with what to do about it."""
    if error is None:
        return (
            "<b>No chamber answered.</b> Check the chamber is switched on and that "
            "no fault is showing on the controller, then try again."
        )
    holders = getattr(error, "holders", ())
    which = (
        f"<p>The port is currently held by: <b>{', '.join(holders)}</b>.</p>"
        if holders
        else ""
    )
    steps = "".join(f"<li>{step}</li>" for step in error.steps)
    port = f" on {error.port}" if error.port else ""
    return f"<b>{error.headline}{port}.</b>{which}<ol>{steps}</ol>"


class RecipePage(QWidget):
    """Choose the test. Every value is editable; nothing is fixed at 48 hours."""

    start = Signal(object, str, str)   # recipe, batch, operator
    back = Signal()

    def __init__(self, recipe: Recipe, operator: str = "") -> None:
        super().__init__()
        self._profile: ChamberProfile | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 32, 48, 28)
        layout.setSpacing(10)
        layout.addWidget(title("Choose the test"))

        self.summary = subtitle("")
        layout.addWidget(self.summary)

        # What the chamber has actually been measured doing, if anyone has run
        # the capability test. A ramp the chamber cannot follow becomes a step
        # change and the recorded profile stops meaning anything.
        self.capability_note = QLabel("")
        self.capability_note.setWordWrap(True)
        self.capability_note.setTextFormat(Qt.RichText)
        self.capability_note.setObjectName("StatusWarn")
        self.capability_note.hide()
        layout.addWidget(self.capability_note)

        self.use_measured = QPushButton("Use the measured times")
        self.use_measured.clicked.connect(self._apply_measured)
        self.use_measured.hide()
        layout.addWidget(self.use_measured, alignment=Qt.AlignLeft)

        form = QWidget()
        f = QVBoxLayout(form)
        f.setContentsMargins(0, 8, 0, 0)
        f.setSpacing(8)

        self.batch = QLineEdit()
        self.batch.setPlaceholderText("Board batch name, e.g. MS-4412")
        self.batch.textChanged.connect(self._update_summary)
        f.addWidget(field_row("Board batch", self.batch))

        self.operator = QLineEdit(operator)
        self.operator.setPlaceholderText("Your name")
        f.addWidget(field_row("Operator", self.operator))

        # --- how long -------------------------------------------------------
        mode = QWidget()
        mode_row = QHBoxLayout(mode)
        mode_row.setContentsMargins(0, 0, 0, 0)
        self.by_cycles = QRadioButton("cycles")
        self.by_hours = QRadioButton("hours")
        self.by_cycles.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.by_cycles)
        group.addButton(self.by_hours)

        self.cycles = int_spin(recipe.cycles, 1, 999)
        self.hours = spin(recipe.total_hours, 0.5, 2000, step=1, decimals=1, suffix=" h")
        self.hours.setEnabled(False)
        mode_row.addWidget(self.by_cycles)
        mode_row.addWidget(self.cycles)
        mode_row.addSpacing(12)
        mode_row.addWidget(self.by_hours)
        mode_row.addWidget(self.hours)
        mode_row.addStretch(1)
        f.addWidget(field_row("Run length", mode,
                              "Set the number of cycles, or a total time and let "
                              "the program work out the cycles."))

        self.by_cycles.toggled.connect(self._mode_changed)
        self.cycles.valueChanged.connect(self._update_summary)
        self.hours.valueChanged.connect(self._update_summary)

        # --- temperatures ---------------------------------------------------
        self.cold = spin(recipe.cold_c, -80, 50, decimals=1, suffix=" °C")
        self.hot = spin(recipe.hot_c, -20, 200, decimals=1, suffix=" °C")
        f.addWidget(field_row("Cold setpoint", self.cold))
        f.addWidget(field_row("Hot setpoint", self.hot))

        self.ramp_down = spin(recipe.ramp_down_minutes, 1, 1440, decimals=0, suffix=" min")
        self.ramp_up = spin(recipe.ramp_up_minutes, 1, 1440, decimals=0, suffix=" min")
        f.addWidget(field_row("Time to cool", self.ramp_down,
                              "Chambers usually cool more slowly than they heat, "
                              "especially with cable ports open."))
        f.addWidget(field_row("Time to heat", self.ramp_up))

        self.cold_dwell = spin(recipe.cold_dwell_minutes, 1, 1440, decimals=0, suffix=" min")
        self.hot_dwell = spin(recipe.hot_dwell_minutes, 1, 1440, decimals=0, suffix=" min")
        f.addWidget(field_row("Hold at cold", self.cold_dwell))
        f.addWidget(field_row("Hold at hot", self.hot_dwell))

        self.soak = check(
            "Wait until the chamber actually reaches temperature before counting a hold",
            recipe.guaranteed_soak,
        )
        f.addWidget(field_row("Guaranteed soak", self.soak,
                              "On: a slow chamber makes the run longer rather than "
                              "cutting the hold short."))

        # --- advanced -------------------------------------------------------
        self.show_advanced = check("Show advanced values", False)
        f.addWidget(self.show_advanced)

        self.advanced = QWidget()
        a = QVBoxLayout(self.advanced)
        a.setContentsMargins(0, 0, 0, 0)
        a.setSpacing(8)
        self.tolerance = spin(recipe.tolerance_c, 0.1, 20, step=0.5, decimals=1, suffix=" °C")
        self.idle = spin(recipe.idle_c, -20, 60, decimals=0, suffix=" °C")
        self.start_from = spin(recipe.start_from_c, -20, 60, decimals=0, suffix=" °C")
        a.addWidget(field_row("Hold tolerance", self.tolerance,
                              "How close counts as being at temperature."))
        a.addWidget(field_row("Return to when finished", self.idle))
        a.addWidget(field_row("Assumed starting temperature", self.start_from,
                              "Where the first cooling ramp starts from."))
        self.advanced.setVisible(False)
        self.show_advanced.toggled.connect(self.advanced.setVisible)
        f.addWidget(self.advanced)

        for widget in (self.cold, self.hot, self.ramp_down, self.ramp_up,
                       self.cold_dwell, self.hot_dwell, self.tolerance,
                       self.idle, self.start_from):
            widget.valueChanged.connect(self._update_summary)
        self.soak.toggled.connect(self._update_summary)

        scroll = QScrollArea()
        scroll.setWidget(form)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        self.go = primary("Continue")
        self.go.clicked.connect(self._emit_start)
        buttons.addWidget(self.go)
        buttons.addStretch(1)
        back = QPushButton("Back")
        back.clicked.connect(self.back)
        buttons.addWidget(back)
        layout.addLayout(buttons)

        self.reload_profiles()
        self._update_summary()

    def reload_profiles(self, model: str = "", serial: str = "") -> None:
        """Use the measurement for the chamber actually in front of the user.

        A loaded test is preferred over an empty one: the empty chamber is the
        best case, not the case the boards will see.
        """
        if model and serial:
            self._profile = best_profile_for(model, serial)
        else:
            profiles = [p for p in load_profiles() if not p.aborted]
            loaded = [p for p in profiles if p.loaded]
            self._profile = (loaded or profiles or [None])[0]
        self._update_summary()

    def _apply_measured(self) -> None:
        if self._profile is None:
            return
        down = self._profile.recommended_minutes(self.hot.value(), self.cold.value())
        up = self._profile.recommended_minutes(self.cold.value(), self.hot.value())
        if down:
            self.ramp_down.setValue(down)
        if up:
            self.ramp_up.setValue(up)

    def _check_against_profile(self, recipe: Recipe) -> None:
        profile = self._profile
        if profile is None:
            self.capability_note.hide()
            self.use_measured.hide()
            return

        problems: list[str] = []
        if not profile.can_reach(recipe.cold_c):
            problems.append(
                f"the coldest it reached was {profile.reachable_min_c:.1f} \u00b0C, "
                f"so {recipe.cold_c:g} \u00b0C is below what it managed"
            )
        if not profile.can_reach(recipe.hot_c):
            problems.append(
                f"the hottest it reached was {profile.reachable_max_c:.1f} \u00b0C, "
                f"so {recipe.hot_c:g} \u00b0C is above what it managed"
            )

        needs_down = profile.minutes_to_traverse(recipe.hot_c, recipe.cold_c)
        needs_up = profile.minutes_to_traverse(recipe.cold_c, recipe.hot_c)
        if needs_down and recipe.ramp_down_minutes < needs_down:
            problems.append(
                f"cooling needs about {needs_down:.0f} min, not "
                f"{recipe.ramp_down_minutes:.0f}"
            )
        if needs_up and recipe.ramp_up_minutes < needs_up:
            problems.append(
                f"heating needs about {needs_up:.0f} min, not "
                f"{recipe.ramp_up_minutes:.0f}"
            )

        if not problems:
            self.capability_note.hide()
            self.use_measured.hide()
            return

        self.capability_note.setText(
            f"<b>{profile.chamber_label} \u2014 measured in "
            f"\u201c{profile.name}\u201d:</b> "
            + "; ".join(problems)
            + ". A ramp the chamber cannot follow becomes a step change, and the "
            "recorded profile stops meaning anything."
        )
        self.capability_note.show()
        self.use_measured.setVisible(bool(needs_down or needs_up))

    def _mode_changed(self) -> None:
        by_cycles = self.by_cycles.isChecked()
        self.cycles.setEnabled(by_cycles)
        self.hours.setEnabled(not by_cycles)
        self._update_summary()

    def recipe(self) -> Recipe:
        base = Recipe(
            cycles=max(1, self.cycles.value()),
            cold_c=self.cold.value(),
            hot_c=self.hot.value(),
            ramp_down_minutes=self.ramp_down.value(),
            ramp_up_minutes=self.ramp_up.value(),
            cold_dwell_minutes=self.cold_dwell.value(),
            hot_dwell_minutes=self.hot_dwell.value(),
            tolerance_c=self.tolerance.value(),
            guaranteed_soak=self.soak.isChecked(),
            idle_c=self.idle.value(),
            start_from_c=self.start_from.value(),
        )
        if self.by_hours.isChecked():
            base = base.with_duration_hours(self.hours.value())
        return base

    def _update_summary(self) -> None:
        try:
            recipe = self.recipe()
        except ValueError as exc:
            self.summary.setText(str(exc))
            self.summary.setObjectName("StatusBad")
            self.summary.style().polish(self.summary)
            self.go.setEnabled(False)
            return

        self.summary.setObjectName("Subtitle")
        self.summary.style().polish(self.summary)
        self.go.setEnabled(bool(self.batch.text().strip()))

        if self.by_hours.isChecked():
            self.cycles.blockSignals(True)
            self.cycles.setValue(recipe.cycles)
            self.cycles.blockSignals(False)

        self._check_against_profile(recipe)

        finish = datetime.now() + timedelta(seconds=recipe.total_seconds)
        self.summary.setText(
            f"{recipe.cycles} cycle{'s' if recipe.cycles != 1 else ''} between "
            f"{recipe.cold_c:g} °C and {recipe.hot_c:g} °C — cooling at "
            f"{recipe.cooling_c_per_min:.2f} °C/min, heating at "
            f"{recipe.heating_c_per_min:.2f} °C/min. "
            f"Total {format_duration(recipe.total_seconds)}, finishing "
            f"{finish.strftime('%A %d %b at %I:%M %p').lstrip('0')}."
        )

    def _emit_start(self) -> None:
        self.start.emit(
            self.recipe(), self.batch.text().strip(), self.operator.text().strip()
        )
