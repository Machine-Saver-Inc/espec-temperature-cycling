"""Settings: every value the program uses, in one place.

Nothing the run depends on is a constant buried in the code. A controller that
has been reconfigured, a chamber that needs a gentler runaway threshold, a
slower serial link -- all of it is changed here rather than in a rebuild.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from espec_burnin.core.run_controller import RunTuning
from espec_burnin.hardware.f4 import PARITY_CHOICES, ConnectionSettings
from espec_burnin.ui.widgets import (
    check,
    choice,
    field_row,
    int_spin,
    primary,
    spin,
    subtitle,
    title,
)

BAUD_RATES = ["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"]

# Outside this, a setpoint is not a burn-in profile, it is a mistake.
SANE_CLAMP_MIN = -80.0
SANE_CLAMP_MAX = 200.0


def _page(*rows: QWidget) -> QWidget:
    inner = QWidget()
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(4, 12, 4, 12)
    layout.setSpacing(12)
    for row in rows:
        layout.addWidget(row)
    layout.addStretch(1)

    scroll = QScrollArea()
    scroll.setWidget(inner)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    return scroll


class SettingsPage(QWidget):
    saved = Signal(object, object)   # ConnectionSettings, RunTuning
    back = Signal()

    def __init__(self, connection: ConnectionSettings, tuning: RunTuning) -> None:
        super().__init__()
        self._defaults_connection = ConnectionSettings()
        self._defaults_tuning = RunTuning()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 28)
        layout.setSpacing(10)
        layout.addWidget(title("Settings"))
        layout.addWidget(
            subtitle(
                "These rarely need changing. They exist so that a reconfigured "
                "controller or an unusual chamber does not need a new build."
            )
        )

        tabs = QTabWidget()
        tabs.addTab(self._connection_tab(connection), "Connection")
        tabs.addTab(self._run_tab(tuning), "Run behaviour")
        tabs.addTab(self._safety_tab(tuning), "Safety limits")
        layout.addWidget(tabs, 1)

        buttons = QHBoxLayout()
        save = primary("Save")
        save.clicked.connect(self._emit_saved)
        buttons.addWidget(save)

        restore = QPushButton("Restore defaults")
        restore.clicked.connect(self._restore_defaults)
        buttons.addWidget(restore)

        buttons.addStretch(1)
        back = QPushButton("Back")
        back.clicked.connect(self.back)
        buttons.addWidget(back)
        layout.addLayout(buttons)

    # -- tabs ----------------------------------------------------------------
    def _connection_tab(self, c: ConnectionSettings) -> QWidget:
        self.slave = int_spin(c.slave_address, 1, 247)
        self.baud = choice(BAUD_RATES, str(c.baudrate))
        self.bytesize = choice(["5", "6", "7", "8"], str(c.bytesize))
        self.parity = choice(list(PARITY_CHOICES), c.parity)
        self.stopbits = choice(["1", "2"], str(c.stopbits))
        self.timeout = spin(c.timeout_s, 0.05, 5.0, step=0.05, decimals=2, suffix=" s")
        self.retries = int_spin(c.retries, 1, 10)
        self.write_fc = choice(["16", "6"], str(c.write_functioncode))
        self.close_after = check(
            "Close the port between messages", c.close_port_after_each_call
        )
        self.plaus_min = spin(c.plausible_min_c, -200, 0, decimals=0, suffix=" °C")
        self.plaus_max = spin(c.plausible_max_c, 0, 1000, decimals=0, suffix=" °C")

        return _page(
            field_row("Controller address", self.slave,
                      "The Watlow F4's Modbus address. 201 unless it has been changed."),
            field_row("Baud rate", self.baud),
            field_row("Data bits", self.bytesize),
            field_row("Parity", self.parity),
            field_row("Stop bits", self.stopbits),
            field_row("Reply timeout", self.timeout,
                      "How long to wait for the controller. Too short and a slow "
                      "reply looks like a dead chamber."),
            field_row("Retries per message", self.retries),
            field_row("Setpoint write function", self.write_fc,
                      "16 works on most F4s. Switch to 6 if setpoint writes are "
                      "refused."),
            field_row("Port handling", self.close_after,
                      "Needed on Windows. Can usually be turned off on Linux."),
            field_row("Lowest believable reading", self.plaus_min,
                      "A reply outside this range is treated as the wrong device "
                      "answering, not as a temperature."),
            field_row("Highest believable reading", self.plaus_max),
        )

    def _run_tab(self, t: RunTuning) -> QWidget:
        self.sample = spin(t.sample_interval_s, 0.2, 60.0, step=0.5, decimals=1, suffix=" s")
        self.epsilon = spin(t.setpoint_epsilon_c, 0.1, 5.0, step=0.1, decimals=1, suffix=" °C")
        self.grace = spin(t.comms_grace_minutes, 1, 240, decimals=0, suffix=" min")
        self.max_extension = spin(t.max_extension_percent, 0, 500, decimals=0, suffix=" %")

        return _page(
            field_row("Sample interval", self.sample,
                      "How often the chamber is read and logged."),
            field_row("Setpoint write threshold", self.epsilon,
                      "Setpoint changes smaller than this are not sent, to keep "
                      "the serial link quiet."),
            field_row("Give up after silence of", self.grace,
                      "How long the chamber may stay unreachable before the run "
                      "is marked failed. The run keeps retrying throughout."),
            field_row("Allow the run to stretch by", self.max_extension,
                      "Guaranteed soak extends a run when the chamber is behind. "
                      "Past this much extra, the run is failed rather than "
                      "stretching for ever. Set to 0 for no limit."),
        )

    def _safety_tab(self, t: RunTuning) -> QWidget:
        self.clamp_min = spin(t.absolute_min_c, SANE_CLAMP_MIN, 0, decimals=0, suffix=" °C")
        self.clamp_max = spin(t.absolute_max_c, 0, SANE_CLAMP_MAX, decimals=0, suffix=" °C")
        self.runaway_delta = spin(t.runaway_delta_c, 1, 100, decimals=0, suffix=" °C")
        self.runaway_for = spin(t.runaway_for_minutes, 1, 120, decimals=0, suffix=" min")

        warning = subtitle(
            "This program is not a safety system. The chamber's own "
            "over-temperature limit controller is the protective device and must "
            "be set correctly before any unattended run."
        )
        warning.setObjectName("StatusWarn")

        return _page(
            warning,
            field_row("Never command below", self.clamp_min,
                      "The program refuses to send a setpoint outside these limits, "
                      "whatever the recipe asks for."),
            field_row("Never command above", self.clamp_max),
            field_row("Runaway if off target by", self.runaway_delta,
                      "During a dwell only. Ramps are expected to lag."),
            field_row("...for longer than", self.runaway_for),
        )

    # -- actions -------------------------------------------------------------
    def values(self) -> tuple[ConnectionSettings, RunTuning]:
        connection = ConnectionSettings(
            slave_address=self.slave.value(),
            baudrate=int(self.baud.currentText()),
            bytesize=int(self.bytesize.currentText()),
            parity=self.parity.currentText(),
            stopbits=int(self.stopbits.currentText()),
            timeout_s=self.timeout.value(),
            retries=self.retries.value(),
            write_functioncode=int(self.write_fc.currentText()),
            close_port_after_each_call=self.close_after.isChecked(),
            plausible_min_c=self.plaus_min.value(),
            plausible_max_c=self.plaus_max.value(),
        )
        tuning = RunTuning(
            sample_interval_s=self.sample.value(),
            setpoint_epsilon_c=self.epsilon.value(),
            comms_grace_minutes=self.grace.value(),
            max_extension_percent=self.max_extension.value(),
            runaway_delta_c=self.runaway_delta.value(),
            runaway_for_minutes=self.runaway_for.value(),
            absolute_min_c=self.clamp_min.value(),
            absolute_max_c=self.clamp_max.value(),
        )
        return connection, tuning

    def _emit_saved(self) -> None:
        connection, tuning = self.values()
        d = self._defaults_tuning
        widened = (
            tuning.absolute_min_c < d.absolute_min_c
            or tuning.absolute_max_c > d.absolute_max_c
        )
        if widened:
            answer = QMessageBox.warning(
                self,
                "Widen the temperature limits?",
                f"You are allowing the program to command "
                f"{tuning.absolute_min_c:g} °C to {tuning.absolute_max_c:g} °C, "
                f"beyond the usual {d.absolute_min_c:g} to {d.absolute_max_c:g} °C.\n\n"
                "Make sure the chamber and the boards can take it, and that the "
                "over-temperature limit controller is set accordingly.",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                return
        self.saved.emit(connection, tuning)

    def _restore_defaults(self) -> None:
        if QMessageBox.question(
            self, "Restore defaults?",
            "Put every setting back to the values the program shipped with?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        ) != QMessageBox.Yes:
            return
        c, t = self._defaults_connection, self._defaults_tuning
        self.slave.setValue(c.slave_address)
        self.baud.setCurrentText(str(c.baudrate))
        self.bytesize.setCurrentText(str(c.bytesize))
        self.parity.setCurrentText(c.parity)
        self.stopbits.setCurrentText(str(c.stopbits))
        self.timeout.setValue(c.timeout_s)
        self.retries.setValue(c.retries)
        self.write_fc.setCurrentText(str(c.write_functioncode))
        self.close_after.setChecked(c.close_port_after_each_call)
        self.plaus_min.setValue(c.plausible_min_c)
        self.plaus_max.setValue(c.plausible_max_c)
        self.sample.setValue(t.sample_interval_s)
        self.epsilon.setValue(t.setpoint_epsilon_c)
        self.grace.setValue(t.comms_grace_minutes)
        self.max_extension.setValue(t.max_extension_percent)
        self.runaway_delta.setValue(t.runaway_delta_c)
        self.runaway_for.setValue(t.runaway_for_minutes)
        self.clamp_min.setValue(t.absolute_min_c)
        self.clamp_max.setValue(t.absolute_max_c)
