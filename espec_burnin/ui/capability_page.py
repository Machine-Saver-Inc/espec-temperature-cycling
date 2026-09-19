"""Measure what the chamber can actually do, and save it as a profile."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
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
    load_profiles_for,
    save_profile,
)
from espec_burnin.core.chambers import (
    Chamber,
    known_models,
    save_chamber,
    serials_for_model,
)
from espec_burnin.core.profile import format_duration
from espec_burnin.ui.widgets import (
    TEXT_WIDTH,
    FieldGroup,
    check,
    cycle_grid,
    editable_choice,
    field_row,
    primary,
    spin,
    subtitle,
    title,
)

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
    start_requested = Signal(object, object, str, bool, str)  # settings, Chamber, test name, loaded, notes

    def __init__(self, tuning=None) -> None:
        super().__init__()
        from espec_burnin.core.run_controller import RunTuning

        self.tuning = tuning or RunTuning()
        self._chamber = Chamber()
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
        f.setContentsMargins(0, 12, 0, 0)
        f.setSpacing(22)

        # --- which chamber. This is the identity everything hangs off. -----
        chamber_box = FieldGroup(
            "Which chamber",
            "Identified the way the floor identifies it. Everything measured "
            "here is saved against this model and serial.",
        )
        self.model = editable_choice(known_models(), placeholder="e.g. Espec BTZ-133")
        self.model.setMaximumWidth(TEXT_WIDTH)
        self.model.currentTextChanged.connect(self._model_changed)
        chamber_box.add(field_row(
            "Model", self.model,
            "Pick one you have used before, or type a new one."))

        self.serial = editable_choice([], placeholder="e.g. 0612223")
        self.serial.setMaximumWidth(TEXT_WIDTH)
        self.serial.currentTextChanged.connect(self._chamber_changed)
        chamber_box.add(field_row("Serial number", self.serial))

        self.recognised = QLabel("")
        self.recognised.setObjectName("StatusGood")
        self.recognised.setWordWrap(True)
        chamber_box.add(self.recognised)
        f.addWidget(chamber_box)

        # --- which test on that chamber -------------------------------------
        self.test_box = FieldGroup(
            "This test",
            "One chamber can hold several tests - loaded and empty measure "
            "different things.",
        )
        self.name = editable_choice([], placeholder="e.g. Loaded \u2014 12 boards")
        self.name.setMaximumWidth(TEXT_WIDTH)
        self.test_box.add(field_row(
            "Test name", self.name,
            "Re-using a name replaces that saved test."))

        self.loaded = check("The chamber is loaded as it will be for a real run", True)
        self.test_box.add(field_row("Setup", self.loaded))

        self.notes = QLineEdit()
        self.notes.setPlaceholderText(
            "e.g. 12 boards on the middle shelf, 2 cables through the left port")
        self.test_box.add(field_row("What is in it", self.notes, stretch=True))

        self.previous_label = QLabel("Already saved for this chamber")
        self.previous_label.setObjectName("Hint")
        self.test_box.add(self.previous_label)

        self.previous = QListWidget()
        self.previous.setMinimumHeight(96)
        self.previous.setMaximumHeight(120)
        self.previous.itemSelectionChanged.connect(self._previous_selected)
        self.test_box.add(self.previous)
        f.addWidget(self.test_box)

        # --- how far to drive it --------------------------------------------
        # Bounded by the safety clamp: measuring the chamber is still driving
        # the chamber, so it cannot command what a run is forbidden to.
        low = self.tuning.absolute_min_c
        high = self.tuning.absolute_max_c
        self.cold_target = spin(low, low, 20, decimals=0, suffix=" °C")
        self.hot_target = spin(high, 20, high, decimals=0, suffix=" °C")
        targets = FieldGroup(
            "How far to drive it",
            "Aim a little beyond the recipe you want to run, so the test finds "
            "the real limit rather than stopping where you asked.",
        )
        holder = QWidget()
        holder_row = QHBoxLayout(holder)
        holder_row.setContentsMargins(0, 0, 0, 0)
        holder_row.addWidget(cycle_grid([("Drive to", self.cold_target, self.hot_target)]))
        holder_row.addStretch(1)
        targets.add(holder)
        targets.add_note(
            f"Limited to {low:g} °C and {high:g} °C by the safety limits in "
            f"Settings. Measuring the chamber is still driving the chamber, so it "
            f"cannot command what a run is forbidden to."
        )
        f.addWidget(targets)
        f.addWidget(subtitle(
            "The test stops each direction when the chamber stops making progress, "
            "so it finds the true limit. Expect it to take a few hours."
        ))
        f.addStretch(1)

        # Without this the page squeezes its own controls when the window is
        # short: the combo boxes lose their descenders and the list of saved
        # tests collapses to a sliver. A form that will not fit should scroll.
        scroll = QScrollArea()
        scroll.setWidget(form)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(scroll, 1)

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

    # -- chamber and test bookkeeping ----------------------------------------
    def set_chamber(self, chamber: Chamber | None) -> None:
        """Pre-fill from the chamber recognised on the connected adapter."""
        self._chamber = chamber or Chamber()
        if self._chamber.is_named:
            self.model.setCurrentText(self._chamber.model)
            self.serial.setCurrentText(self._chamber.serial)
            self.recognised.setText(
                f"Recognised from the adapter you are connected through: "
                f"{self._chamber.label}.")
        else:
            self.recognised.setText("")
        self._refresh_previous()

    def _model_changed(self, model: str) -> None:
        known = serials_for_model(model)
        current = self.serial.currentText()
        self.serial.blockSignals(True)
        self.serial.clear()
        self.serial.addItems(known)
        self.serial.setCurrentText(current if current in known else current)
        self.serial.blockSignals(False)
        self._chamber_changed()

    def _chamber_changed(self, *_args) -> None:
        self._refresh_previous()

    def chamber(self) -> Chamber:
        return Chamber(
            model=self.model.currentText().strip(),
            serial=self.serial.currentText().strip(),
            adapter_serial=self._chamber.adapter_serial,
            last_port=self._chamber.last_port,
        )

    def _refresh_previous(self) -> None:
        chamber = self.chamber()
        self.previous.clear()
        names = []
        if chamber.is_named:
            for profile in load_profiles_for(chamber.model, chamber.serial):
                names.append(profile.name)
                reached = ""
                if profile.reachable_min_c is not None and profile.reachable_max_c is not None:
                    reached = (f"  \u00b7  reached {profile.reachable_min_c:.0f} to "
                               f"{profile.reachable_max_c:.0f} °C")
                when = profile.measured_at.replace("T", " ")[:16]
                self.previous.addItem(f"{profile.name}  \u00b7  {when}{reached}")

        self.previous_label.setText(
            f"Tests already saved for {chamber.label}" if names
            else "No tests saved for this chamber yet")
        current = self.name.currentText()
        self.name.blockSignals(True)
        self.name.clear()
        self.name.addItems(names)
        self.name.setCurrentText(current)
        self.name.blockSignals(False)

    def _previous_selected(self) -> None:
        item = self.previous.currentItem()
        if item:
            self.name.setCurrentText(item.text().split("  \u00b7  ")[0])

    def _emit_start(self) -> None:
        chamber = self.chamber()
        if not chamber.is_named:
            QMessageBox.information(
                self, "Which chamber is this?",
                "Enter the chamber's model and serial number first. The "
                "measurement is saved against that chamber so it can be found "
                "again, and so a recipe is checked against the right one.",
            )
            return

        settings = CapabilitySettings(
            cold_target_c=self.cold_target.value(),
            hot_target_c=self.hot_target.value(),
            absolute_min_c=self.tuning.absolute_min_c,
            absolute_max_c=self.tuning.absolute_max_c,
        )
        save_chamber(chamber)
        self.start_requested.emit(
            settings, chamber,
            self.name.currentText().strip() or "Test",
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

        self.open_folder = QPushButton("Open the measurement data")
        self.open_folder.clicked.connect(self._open_folder)
        self.open_folder.hide()
        buttons.addWidget(self.open_folder)

        buttons.addStretch(1)
        discard = QPushButton("Discard")
        discard.clicked.connect(lambda: self.finished.emit(None))
        buttons.addWidget(discard)
        layout.addLayout(buttons)
        return page

    def show_result(self, profile: ChamberProfile, folder=None) -> None:
        self._profile = profile
        self._folder = folder
        self.open_folder.setVisible(folder is not None)
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
            "<p><b>The test was stopped early, so this profile is incomplete.</b> "
            "Every sample taken up to that point was still written to disk.</p>"
            if profile.aborted else ""
        )

        self.result_body.setText(
            f"<h3>{profile.name}</h3>{aborted}{limits}{suggestion}"
            "<h4>Cooling</h4>" + table(profile.cooling_rates, Direction.COOLING) +
            "<h4>Heating</h4>" + table(profile.heating_rates, Direction.HEATING) +
            "<p>Speed falls off near the extremes, which is why a single average "
            "figure overpromises. The recipe screen uses the whole curve.</p>"
        )

    def _open_folder(self) -> None:
        import webbrowser

        if self._folder is not None:
            webbrowser.open(self._folder.as_uri())

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
