"""The screens. One obvious action on each."""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from espec_burnin.core.profile import Recipe, format_duration
from espec_burnin.hardware import ports as ports_mod


def title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Title")
    return label


def subtitle(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Subtitle")
    label.setWordWrap(True)
    return label


def primary(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("Primary")
    return button


class ProbeWorker(QThread):
    """Port probing off the GUI thread, so a dead port never freezes the window."""

    found = Signal(object, float)
    not_found = Signal()

    def __init__(self, device: str | None = None) -> None:
        super().__init__()
        self.device = device

    def run(self) -> None:
        if self.device:
            temperature = ports_mod.probe_port(self.device)
            if temperature is None:
                self.not_found.emit()
            else:
                match = next(
                    (p for p in ports_mod.list_serial_ports() if p.device == self.device),
                    None,
                )
                self.found.emit(match, temperature)
            return
        result = ports_mod.autodetect()
        if result is None:
            self.not_found.emit()
        else:
            self.found.emit(result[0], result[1])


class HomePage(QWidget):
    start_requested = Signal()
    results_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(14)
        layout.addStretch(1)
        layout.addWidget(title("Espec Burn-In"))
        layout.addWidget(
            subtitle("Temperature cycling for PCB burn-in, −20 °C to +80 °C.")
        )
        layout.addSpacing(24)

        start = primary("Start a burn-in run")
        start.clicked.connect(self.start_requested)
        layout.addWidget(start, alignment=Qt.AlignLeft)

        results = QPushButton("Open past results")
        results.clicked.connect(self.results_requested)
        layout.addWidget(results, alignment=Qt.AlignLeft)

        layout.addStretch(2)
        self.status = QLabel("")
        self.status.setObjectName("StatusGood")
        layout.addWidget(self.status)

    def set_connection(self, text: str, ok: bool) -> None:
        self.status.setText(text)
        self.status.setObjectName("StatusGood" if ok else "StatusWarn")
        self.status.style().polish(self.status)


class ConnectPage(QWidget):
    """Port selection, auto-detect, and the no-ports-found guidance."""

    connected = Signal(object)
    back = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._worker: ProbeWorker | None = None
        self._ports: list = []

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
        self._start_worker(ProbeWorker(port.device))

    def _autodetect(self) -> None:
        self._busy(True, "Looking for the chamber on each port…")
        self._start_worker(ProbeWorker(None))

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

    def _on_not_found(self) -> None:
        self.result.setText(
            "No chamber answered. Check the chamber is switched on and that no fault "
            "is showing on the controller, then try again."
        )
        self.result.setObjectName("StatusBad")
        self.result.style().polish(self.result)


class RecipePage(QWidget):
    start = Signal(object, str, str)   # recipe, batch, operator
    back = Signal()

    def __init__(self, recipe: Recipe, operator: str = "") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 40, 48, 40)
        layout.setSpacing(12)
        layout.addWidget(title("Choose the test"))

        self.summary = subtitle("")
        layout.addWidget(self.summary)
        layout.addSpacing(8)

        form = QVBoxLayout()
        form.setSpacing(8)

        self.batch = QLineEdit()
        self.batch.setPlaceholderText("Board batch name, e.g. MS-4412")
        self.batch.textChanged.connect(self._update_summary)
        form.addLayout(self._row("Board batch", self.batch))

        self.operator = QLineEdit(operator)
        self.operator.setPlaceholderText("Your name")
        form.addLayout(self._row("Operator", self.operator))

        self.cycles = QSpinBox()
        self.cycles.setRange(1, 200)
        self.cycles.setValue(recipe.cycles)
        self.cycles.valueChanged.connect(self._update_summary)
        form.addLayout(self._row("Cycles", self.cycles))

        self.cold = QDoubleSpinBox()
        self.cold.setRange(-25, 0)
        self.cold.setSuffix(" °C")
        self.cold.setValue(recipe.cold_c)
        self.cold.valueChanged.connect(self._update_summary)
        form.addLayout(self._row("Cold setpoint", self.cold))

        self.hot = QDoubleSpinBox()
        self.hot.setRange(0, 85)
        self.hot.setSuffix(" °C")
        self.hot.setValue(recipe.hot_c)
        self.hot.valueChanged.connect(self._update_summary)
        form.addLayout(self._row("Hot setpoint", self.hot))

        self.ramp = QDoubleSpinBox()
        self.ramp.setRange(5, 600)
        self.ramp.setSuffix(" min")
        self.ramp.setValue(recipe.ramp_minutes)
        self.ramp.valueChanged.connect(self._update_summary)
        form.addLayout(self._row("Ramp time", self.ramp))

        self.dwell = QDoubleSpinBox()
        self.dwell.setRange(5, 600)
        self.dwell.setSuffix(" min")
        self.dwell.setValue(recipe.cold_dwell_minutes)
        self.dwell.valueChanged.connect(self._update_summary)
        form.addLayout(self._row("Dwell at each end", self.dwell))

        self.soak = QCheckBox(
            "Wait for the chamber to actually reach temperature before counting the dwell"
        )
        self.soak.setChecked(recipe.guaranteed_soak)
        self.soak.setToolTip(
            "On: a slow chamber makes the run longer rather than shortening the dwell.\n"
            "Off: the run takes exactly the scheduled time whatever the chamber does."
        )
        form.addWidget(self.soak)
        layout.addLayout(form)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        self.go = primary("Continue")
        self.go.clicked.connect(self._emit_start)
        buttons.addWidget(self.go)
        buttons.addStretch(1)
        back = QPushButton("Back")
        back.clicked.connect(self.back)
        buttons.addWidget(back)
        layout.addLayout(buttons)

        self._update_summary()

    @staticmethod
    def _row(label: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        text = QLabel(label)
        text.setMinimumWidth(170)
        row.addWidget(text)
        row.addWidget(widget, 1)
        return row

    def recipe(self) -> Recipe:
        return Recipe(
            cycles=self.cycles.value(),
            cold_c=self.cold.value(),
            hot_c=self.hot.value(),
            ramp_minutes=self.ramp.value(),
            cold_dwell_minutes=self.dwell.value(),
            hot_dwell_minutes=self.dwell.value(),
            guaranteed_soak=self.soak.isChecked(),
        )

    def _update_summary(self) -> None:
        try:
            recipe = self.recipe()
        except ValueError as exc:
            self.summary.setText(str(exc))
            self.go.setEnabled(False)
            return
        self.go.setEnabled(bool(self.batch.text().strip()))
        finish = datetime.now() + timedelta(seconds=recipe.total_seconds)
        self.summary.setText(
            f"{recipe.cycles} cycles between {recipe.cold_c:g} °C and "
            f"{recipe.hot_c:g} °C, ramping at {recipe.ramp_c_per_min:.2f} °C/min. "
            f"Total {format_duration(recipe.total_seconds)} — starting now, "
            f"finishing {finish.strftime('%A %d %b at %I:%M %p').lstrip('0')}."
        )

    def _emit_start(self) -> None:
        self.start.emit(self.recipe(), self.batch.text().strip(), self.operator.text().strip())
