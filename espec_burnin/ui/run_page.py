"""The running screen, and the troubleshooting panel that replaces it when the
chamber stops answering."""

from __future__ import annotations

import collections

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    import pyqtgraph as pg
except ImportError:  # pragma: no cover - plotting is optional at import time
    pg = None

from espec_burnin.core.profile import format_duration
from espec_burnin.core.run_controller import RunController, RunState, Status

TROUBLESHOOTING_STEPS = [
    (
        "Is the chamber switched on?",
        "The Watlow F4 display on the front of the chamber should be lit and showing a "
        "temperature. If it is dark, turn the chamber's main power on and give the "
        "controller about ten seconds to start.",
    ),
    (
        "Is a fault showing?",
        "If the F4 display is flashing an alarm or error, clear it at the controller "
        "before going further. If the chamber's separate over-temperature limit "
        "controller has tripped, it has to be reset on that limit controller — the F4 "
        "cannot clear it, and the chamber will not heat or cool until it is.",
    ),
    (
        "Check the cable.",
        "The serial cable should be firmly seated at both ends: the communications port "
        "on the chamber, and the USB adapter on this computer.",
    ),
    (
        "Check the port.",
        "Confirm the port below still exists — Device Manager under Ports (COM & LPT) "
        "on Windows, ls /dev/ttyUSB* on Linux. If the adapter has been unplugged and "
        "replugged the name may have changed; Change port will re-detect it.",
    ),
    (
        "Is anything else using the port?",
        "Chamber vendor software, a terminal program such as PuTTY or Tera Term, or a "
        "second copy of this program will hold the port open and lock this one out. "
        "Close them.",
    ),
    (
        "Check the controller's communication settings.",
        "They should read address 201, 19200 baud, 8 data bits, no parity, 1 stop bit. "
        "A controller that has been factory reset will be back at its defaults.",
    ),
]


class RunWorker(QThread):
    """Runs the controller off the GUI thread."""

    status = Signal(object)
    done = Signal(object)

    def __init__(self, controller: RunController) -> None:
        super().__init__()
        self.controller = controller
        self.controller.on_status = self.status.emit

    def run(self) -> None:
        self.done.emit(self.controller.run())

    def stop(self) -> None:
        self.controller.stop()


class TroubleshootingPanel(QFrame):
    retry = Signal()
    change_port = Signal()
    stop_run = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        heading = QLabel("Not getting a temperature from the chamber")
        heading.setObjectName("StatusBad")
        heading.setStyleSheet("font-size: 18px;")
        layout.addWidget(heading)

        note = QLabel(
            "The run has not been abandoned — the program is still trying, and this "
            "panel will close as soon as a reading comes back."
        )
        note.setWordWrap(True)
        note.setObjectName("Subtitle")
        layout.addWidget(note)

        # The steps go in a scroll area: word-wrapped detail text needs more
        # vertical room than the window can guarantee, and a clipped
        # troubleshooting step is worse than no troubleshooting step at all.
        steps = QWidget()
        steps_layout = QVBoxLayout(steps)
        steps_layout.setContentsMargins(0, 0, 8, 0)
        steps_layout.setSpacing(10)
        for index, (step, detail) in enumerate(TROUBLESHOOTING_STEPS, start=1):
            block = QLabel(f"<b>{index}. {step}</b><br>{detail}")
            block.setWordWrap(True)
            block.setTextFormat(Qt.RichText)
            block.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            steps_layout.addWidget(block)
        steps_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(steps)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(300)
        layout.addWidget(scroll, 1)

        self.port_label = QLabel("")
        self.port_label.setObjectName("Subtitle")
        layout.addWidget(self.port_label)

        buttons = QHBoxLayout()
        retry = QPushButton("Try again")
        retry.setObjectName("Primary")
        retry.clicked.connect(self.retry)
        buttons.addWidget(retry)

        change = QPushButton("Change port")
        change.clicked.connect(self.change_port)
        buttons.addWidget(change)

        buttons.addStretch(1)
        stop = QPushButton("Stop the run")
        stop.setObjectName("Danger")
        stop.clicked.connect(self.stop_run)
        buttons.addWidget(stop)
        layout.addLayout(buttons)

    def set_port(self, port: str) -> None:
        self.port_label.setText(f"Using {port}")


class RunPage(QWidget):
    stop_requested = Signal()
    change_port_requested = Signal()

    MAX_POINTS = 200_000

    def __init__(self) -> None:
        super().__init__()
        self._elapsed = collections.deque(maxlen=self.MAX_POINTS)
        self._measured = collections.deque(maxlen=self.MAX_POINTS)
        self._setpoint = collections.deque(maxlen=self.MAX_POINTS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(10)

        self.batch_label = QLabel("")
        self.batch_label.setObjectName("Subtitle")
        layout.addWidget(self.batch_label)

        top = QHBoxLayout()
        self.temperature = QLabel("—")
        self.temperature.setObjectName("BigTemperature")
        top.addWidget(self.temperature)

        column = QVBoxLayout()
        self.target = QLabel("")
        self.target.setObjectName("Target")
        self.phase = QLabel("")
        self.phase.setStyleSheet("font-size: 17px; font-weight: 600;")
        column.addStretch(1)
        column.addWidget(self.phase)
        column.addWidget(self.target)
        column.addStretch(1)
        top.addLayout(column)
        top.addStretch(1)
        layout.addLayout(top)

        self.progress = QLabel("")
        self.progress.setObjectName("Subtitle")
        layout.addWidget(self.progress)

        if pg is not None:
            # Follow the application palette; pyqtgraph's default is black on
            # black, which looks broken inside a light-themed window.
            palette = self.palette()
            pg.setConfigOptions(
                antialias=True,
                background=palette.base().color(),
                foreground=palette.windowText().color(),
            )
            self.plot = pg.PlotWidget()
            self.plot.setLabel("left", "Temperature", units="°C")
            self.plot.setLabel("bottom", "Elapsed", units="h")
            self.plot.showGrid(x=True, y=True, alpha=0.25)
            self.plot.addLegend(offset=(-10, 10))
            self._setpoint_curve = self.plot.plot(
                [], [], pen=pg.mkPen("#9aa4b2", width=1, style=Qt.DashLine), name="Setpoint"
            )
            self._measured_curve = self.plot.plot(
                [], [], pen=pg.mkPen("#2f6feb", width=2), name="Measured"
            )
            layout.addWidget(self.plot, 1)
        else:  # pragma: no cover
            self.plot = None
            layout.addWidget(QLabel("Plotting unavailable (pyqtgraph not installed)"), 1)

        self.panel = TroubleshootingPanel()
        self.panel.hide()
        self.panel.retry.connect(lambda: None)  # the controller retries continuously
        self.panel.change_port.connect(self.change_port_requested)
        self.panel.stop_run.connect(self.stop_requested)
        layout.addWidget(self.panel)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.stop = QPushButton("Stop run")
        self.stop.setObjectName("Danger")
        self.stop.clicked.connect(self.stop_requested)
        buttons.addWidget(self.stop)
        layout.addLayout(buttons)

    def begin(self, batch: str, port: str, total_cycles: int) -> None:
        self._elapsed.clear()
        self._measured.clear()
        self._setpoint.clear()
        self._total_cycles = total_cycles
        self.batch_label.setText(f"Batch {batch} · {port}")
        self.panel.set_port(port)

    def update_status(self, status: Status) -> None:
        if status.measured_c is None:
            self.temperature.setText("No reading")
            self.temperature.setStyleSheet("font-size: 42px;")
        else:
            self.temperature.setText(f"{status.measured_c:.1f} °C")
            self.temperature.setStyleSheet("")
            self._elapsed.append(status.elapsed_s / 3600.0)
            self._measured.append(status.measured_c)
            self._setpoint.append(status.point.setpoint_c)

        self.phase.setText(status.point.phase.label)
        self.target.setText(f"Target {status.point.setpoint_c:.1f} °C")
        self.progress.setText(
            f"Cycle {status.point.cycle} of {self._total_cycles} · "
            f"{format_duration(status.elapsed_s)} elapsed · "
            f"{format_duration(status.remaining_s)} remaining"
        )

        lost = status.state is RunState.COMMS_LOST
        self.panel.setVisible(lost)
        if self.plot is not None:
            self.plot.setVisible(not lost)
            self._redraw()

    def _redraw(self) -> None:
        if self.plot is None or not self._elapsed:
            return
        # 48 hours at 1 Hz is 172,800 points; draw at most a couple of thousand.
        step = max(1, len(self._elapsed) // 2000)
        x = list(self._elapsed)[::step]
        self._measured_curve.setData(x, list(self._measured)[::step])
        self._setpoint_curve.setData(x, list(self._setpoint)[::step])
