"""The running screen, and the troubleshooting panel that replaces it when the
chamber stops answering."""

from __future__ import annotations

import collections

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
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
from espec_burnin.hardware.errors import ChamberError, NoReplyError
from espec_burnin.ui.widgets import button


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
    """What to do about the failure that actually happened.

    "The port is held by another program" and "the chamber is switched off"
    need different answers, so the steps come from the error rather than from a
    single fixed list.
    """

    retry = Signal()
    change_port = Signal()
    stop_run = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._port = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        self.heading = QLabel("")
        self.heading.setObjectName("StatusBad")
        self.heading.setStyleSheet("font-size: 18px;")
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)

        self.note = QLabel(
            "The run has not been abandoned \u2014 the program is still trying, and "
            "this panel will close as soon as a reading comes back."
        )
        self.note.setWordWrap(True)
        self.note.setObjectName("Subtitle")
        layout.addWidget(self.note)

        # Word-wrapped step text needs more vertical room than the window can
        # guarantee, and a clipped troubleshooting step is worse than none.
        self._steps_holder = QWidget()
        self._steps_layout = QVBoxLayout(self._steps_holder)
        self._steps_layout.setContentsMargins(0, 0, 8, 0)
        self._steps_layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidget(self._steps_holder)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(120)
        self._scroll = scroll
        layout.addWidget(scroll, 1)

        self.port_label = QLabel("")
        self.port_label.setObjectName("Subtitle")
        layout.addWidget(self.port_label)

        buttons = QHBoxLayout()
        retry = button("Try again", "refresh")
        retry.setObjectName("Primary")
        retry.clicked.connect(self.retry)
        buttons.addWidget(retry)

        change = button("Change port", "connect")
        change.clicked.connect(self.change_port)
        buttons.addWidget(change)

        buttons.addStretch(1)
        stop = button("Stop the run", "stop", "danger")
        stop.setObjectName("Danger")
        stop.clicked.connect(self.stop_run)
        buttons.addWidget(stop)
        layout.addLayout(buttons)

        self.show_error(None)

    def set_port(self, port: str) -> None:
        self._port = port
        self.port_label.setText(f"Using {port}")

    def show_error(self, error: ChamberError | None) -> None:
        error = error or NoReplyError()
        if self.heading.text() == error.headline:
            return          # same failure, leave the panel alone

        self.heading.setText(error.headline)

        while self._steps_layout.count():
            item = self._steps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # setParent(None) detaches it now; deleteLater alone defers to
                # the event loop and the old steps stay painted underneath.
                widget.setParent(None)
                widget.deleteLater()

        holders = getattr(error, "holders", ())
        if holders:
            found = QLabel(
                "The port is currently held by: <b>" + ", ".join(holders) + "</b>"
            )
            found.setWordWrap(True)
            found.setTextFormat(Qt.RichText)
            self._steps_layout.addWidget(found)

        for index, step in enumerate(error.steps, start=1):
            block = QLabel(f"<b>{index}.</b> {step}".replace("\n", "<br>"))
            block.setWordWrap(True)
            block.setTextFormat(Qt.RichText)
            block.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            self._steps_layout.addWidget(block)
        self._steps_layout.addStretch(1)

        # Size to the steps rather than leaving a large empty box for a short
        # list, while still scrolling for a long one.
        self._steps_holder.adjustSize()
        needed = self._steps_holder.sizeHint().height() + 12
        self._scroll.setMaximumHeight(max(120, min(needed, 380)))


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
        self.stop = button("Stop run", "stop", "danger")
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
        if lost:
            self.panel.show_error(status.error)
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
