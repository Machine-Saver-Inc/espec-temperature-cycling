"""Measure what the chamber can actually do, and save it as a profile."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

try:
    import pyqtgraph as pg
except ImportError:  # pragma: no cover
    pg = None

from espec_burnin.core.capability import (
    CapabilityProgress,
    CapabilitySettings,
    CapabilityTest,
    ChamberProfile,
    Direction,
    save_profile,
)
from espec_burnin.core.profile import format_duration
from espec_burnin.ui.widgets import check, field_row, primary, spin, subtitle, title

SETUP, RUNNING, RESULT = range(3)


class CapabilityWorker(QThread):
    progress = Signal(object)
    done = Signal(object)

    def __init__(self, test: CapabilityTest) -> None:
        super().__init__()
        self.test = test
        self.test.on_progress = self.progress.emit

    def run(self) -> None:
        self.done.emit(self.test.run())

    def stop(self) -> None:
        self.test.stop()


class CapabilityPage(QWidget):
    """Three states: describe the setup, watch it run, read the result."""

    finished = Signal(object)    # ChamberProfile or None
    back = Signal()
    start_requested = Signal(object, str, bool, str)   # settings, name, loaded, notes

    def __init__(self) -> None:
        super().__init__()
        self._elapsed: list[float] = []
        self._temps: list[float] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        self.stack.addWidget(self._setup_page())
        self.stack.addWidget(self._running_page())
        self.stack.addWidget(self._result_page())

    # -- setup ---------------------------------------------------------------
    def _setup_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(48, 40, 48, 32)
        layout.setSpacing(10)
        layout.addWidget(title("Measure the chamber's speed"))
        layout.addWidget(subtitle(
            "The chamber is driven to each extreme and told how fast it actually "
            "moved, band by band. The result is saved as a profile and used to "
            "warn you when a recipe asks for a ramp this chamber cannot follow."
        ))

        note = QLabel(
            "<b>Set the chamber up exactly as it will be for the real run</b> — "
            "same boards, same fixtures, same cables through the entry ports. An "
            "empty chamber with the ports closed measures the best case, not the "
            "case you will run in. Measure both if you want the comparison; they "
            "save as separate profiles."
        )
        note.setWordWrap(True)
        note.setTextFormat(Qt.RichText)
        note.setObjectName("StatusWarn")
        layout.addWidget(note)

        form = QWidget()
        f = QVBoxLayout(form)
        f.setContentsMargins(0, 10, 0, 0)
        f.setSpacing(8)

        self.name = QLineEdit("Loaded — boards and cables")
        f.addWidget(field_row("Profile name", self.name,
                              "How this setup will be listed, e.g. 'Loaded — 12 "
                              "boards' or 'Empty, ports closed'."))

        self.loaded = check("The chamber is loaded as it will be for a real run", True)
        f.addWidget(field_row("Setup", self.loaded))

        self.notes = QLineEdit()
        self.notes.setPlaceholderText("e.g. 12 boards on the middle shelf, 2 cables through the left port")
        f.addWidget(field_row("What is in it", self.notes))

        self.cold_target = spin(-25, -80, 20, decimals=0, suffix=" °C")
        self.hot_target = spin(85, 20, 200, decimals=0, suffix=" °C")
        f.addWidget(field_row("Cool down towards", self.cold_target,
                              "Aim a little beyond your recipe, so the test finds "
                              "the real limit rather than stopping at your target."))
        f.addWidget(field_row("Heat up towards", self.hot_target))
        layout.addWidget(form)

        layout.addWidget(subtitle(
            "The test stops each direction when the chamber stops making progress, "
            "so it finds the true limit. Expect it to take a few hours."
        ))
        layout.addStretch(1)

        buttons = QHBoxLayout()
        go = primary("Start the test")
        go.clicked.connect(self._emit_start)
        buttons.addWidget(go)
        buttons.addStretch(1)
        back = QPushButton("Back")
        back.clicked.connect(self.back)
        buttons.addWidget(back)
        layout.addLayout(buttons)
        return page

    def _emit_start(self) -> None:
        settings = CapabilitySettings(
            cold_target_c=self.cold_target.value(),
            hot_target_c=self.hot_target.value(),
        )
        self.start_requested.emit(
            settings, self.name.text().strip() or "Chamber",
            self.loaded.isChecked(), self.notes.text().strip(),
        )

    # -- running -------------------------------------------------------------
    def _running_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 32, 40, 28)
        layout.setSpacing(10)
        layout.addWidget(title("Measuring"))

        self.live_temp = QLabel("—")
        self.live_temp.setObjectName("BigTemperature")
        layout.addWidget(self.live_temp)

        self.live_message = QLabel("")
        self.live_message.setObjectName("Subtitle")
        self.live_message.setWordWrap(True)
        layout.addWidget(self.live_message)

        self.live_rate = QLabel("")
        layout.addWidget(self.live_rate)

        if pg is not None:
            palette = self.palette()
            pg.setConfigOptions(antialias=True,
                                background=palette.base().color(),
                                foreground=palette.windowText().color())
            self.plot = pg.PlotWidget()
            self.plot.setLabel("left", "Temperature", units="°C")
            self.plot.setLabel("bottom", "Elapsed", units="h")
            self.plot.showGrid(x=True, y=True, alpha=0.25)
            self._curve = self.plot.plot([], [], pen=pg.mkPen("#2f6feb", width=2))
            layout.addWidget(self.plot, 1)
        else:  # pragma: no cover
            self.plot = None
            layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.stop_button = QPushButton("Stop the test")
        self.stop_button.setObjectName("Danger")
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)
        return page

    def show_progress(self, p: CapabilityProgress) -> None:
        self.stack.setCurrentIndex(RUNNING)
        if p.measured_c is not None:
            self.live_temp.setText(f"{p.measured_c:.1f} °C")
            self._elapsed.append(p.elapsed_s / 3600.0)
            self._temps.append(p.measured_c)
            if self.plot is not None:
                self._curve.setData(self._elapsed, self._temps)
        self.live_message.setText(p.message)
        if p.rate_c_per_min is not None:
            self.live_rate.setText(
                f"Currently moving at {abs(p.rate_c_per_min):.2f} °C/min "
                f"· {format_duration(p.elapsed_s)} elapsed"
            )

    # -- result --------------------------------------------------------------
    def _result_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(48, 40, 48, 32)
        layout.setSpacing(10)
        layout.addWidget(title("What the chamber can do"))

        self.result_body = QLabel("")
        self.result_body.setWordWrap(True)
        self.result_body.setTextFormat(Qt.RichText)
        scroll = QScrollArea()
        scroll.setWidget(self.result_body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        self.save_button = primary("Save this profile")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)
        buttons.addStretch(1)
        discard = QPushButton("Discard")
        discard.clicked.connect(lambda: self.finished.emit(None))
        buttons.addWidget(discard)
        layout.addLayout(buttons)
        return page

    def show_result(self, profile: ChamberProfile) -> None:
        self._profile = profile
        self.stack.setCurrentIndex(RESULT)

        def table(rates: dict, direction: Direction) -> str:
            if not rates:
                return "<p>Nothing measured in this direction.</p>"
            rows = "".join(
                f"<tr><td>{float(band):+.0f} °C</td>"
                f"<td align='right'>{rate:.2f} °C/min</td></tr>"
                for band, rate in sorted(rates.items(), key=lambda kv: float(kv[0]),
                                         reverse=direction is Direction.COOLING)
            )
            return (
                "<table cellpadding='4'><tr><th align='left'>Around</th>"
                f"<th align='right'>Speed</th></tr>{rows}</table>"
            )

        cold = profile.reachable_min_c
        hot = profile.reachable_max_c
        limits = (
            f"<p>Coldest it reached: <b>{cold:.1f} °C</b>"
            f" · hottest: <b>{hot:.1f} °C</b></p>"
            if cold is not None and hot is not None else ""
        )

        suggestion = ""
        if cold is not None and hot is not None:
            down = profile.recommended_minutes(hot, cold)
            up = profile.recommended_minutes(cold, hot)
            if down and up:
                suggestion = (
                    f"<p>For a {cold:.0f} °C to {hot:.0f} °C cycle, allow about "
                    f"<b>{down} minutes to cool</b> and <b>{up} minutes to heat</b>. "
                    "That includes a little headroom.</p>"
                )

        aborted = (
            "<p><b>The test was stopped early, so this profile is incomplete.</b></p>"
            if profile.aborted else ""
        )

        self.result_body.setText(
            f"<h3>{profile.name}</h3>{aborted}{limits}{suggestion}"
            "<h4>Cooling</h4>" + table(profile.cooling_rates, Direction.COOLING) +
            "<h4>Heating</h4>" + table(profile.heating_rates, Direction.HEATING) +
            "<p>Speed falls off near the extremes, which is why a single average "
            "figure overpromises. The recipe screen uses the whole curve.</p>"
        )

    def _save(self) -> None:
        try:
            path = save_profile(self._profile)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return
        QMessageBox.information(self, "Saved", f"Profile saved to\n{path}")
        self.finished.emit(self._profile)

    def reset(self) -> None:
        self._elapsed.clear()
        self._temps.clear()
        self.stack.setCurrentIndex(SETUP)
