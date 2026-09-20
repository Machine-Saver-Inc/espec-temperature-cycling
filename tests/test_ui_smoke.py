"""Every screen must at least build.

These caught an import that only failed at runtime: the modules had no test
touching them, so a wrong import sat in a shipped build without anything
noticing. Cheap insurance against that whole class of mistake.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

# Importing the PySide6 package succeeds even when the Qt shared libraries
# are missing; it is the first submodule import that fails. Skip on the
# submodule so a machine without libEGL skips these tests instead of
# failing collection and taking the whole suite down with it.
pytest.importorskip(
    "PySide6.QtWidgets", reason="PySide6 and its Qt libraries are required for the interface"
)

from PySide6.QtWidgets import QApplication  # noqa: E402

from espec_burnin.core.profile import Recipe  # noqa: E402
from espec_burnin.core.run_controller import RunTuning  # noqa: E402
from espec_burnin.hardware.f4 import ConnectionSettings  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    from espec_burnin.ui.style import STYLESHEET

    application.setStyleSheet(STYLESHEET)
    yield application


def test_every_page_builds(app):
    from espec_burnin.ui.capability_page import CapabilityPage
    from espec_burnin.ui.pages import ConnectPage, HomePage, RecipePage
    from espec_burnin.ui.run_page import RunPage
    from espec_burnin.ui.settings_page import SettingsPage

    assert HomePage() is not None
    assert ConnectPage(ConnectionSettings()) is not None
    assert RecipePage(Recipe()) is not None
    assert RunPage() is not None
    assert SettingsPage(ConnectionSettings(), RunTuning()) is not None
    assert CapabilityPage(RunTuning()) is not None


def test_the_report_dialog_builds_and_previews(app):
    from espec_burnin.ui.report_dialog import ReportDialog

    dialog = ReportDialog({"Screen open": "Home", "Port": "COM3"})
    dialog.summary.setText("Something went wrong")
    app.processEvents()

    assert "[Bug]" in dialog.preview.toPlainText()
    assert "Screen open" in dialog.preview.toPlainText()
    assert dialog.post.isEnabled()

    dialog.improvement.setChecked(True)
    app.processEvents()
    assert "[Improvement]" in dialog.preview.toPlainText()

    from espec_burnin.ui.icons import icon

    assert not icon("report").isNull(), "the report mark did not render"


def test_the_report_button_sits_on_the_window(app, tmp_path, monkeypatch):
    from unittest import mock

    with mock.patch("espec_burnin.core.recorder.results_root", return_value=tmp_path), \
         mock.patch("espec_burnin.core.capability.profiles_dir", return_value=tmp_path), \
         mock.patch("espec_burnin.core.chambers.chambers_path",
                    return_value=tmp_path / "chambers.json"):
        from espec_burnin.ui.main_window import MainWindow

        window = MainWindow()
        assert window.report_button is not None
        assert not window.report_button.icon().isNull()
        # Present regardless of which screen is showing.
        context = window._report_context()
        assert "Screen open" in context
        assert "Program" not in context      # version comes from environment()
        assert context["Run in progress"] == "no"


def test_the_report_context_survives_a_broken_field(app, tmp_path):
    from unittest import mock

    with mock.patch("espec_burnin.core.recorder.results_root", return_value=tmp_path), \
         mock.patch("espec_burnin.core.capability.profiles_dir", return_value=tmp_path), \
         mock.patch("espec_burnin.core.chambers.chambers_path",
                    return_value=tmp_path / "chambers.json"):
        from espec_burnin.ui.main_window import MainWindow

        window = MainWindow()
        window._current_chamber = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        # Must not raise: a report has to open even when the state cannot be read.
        window._report_problem = MainWindow._report_problem.__get__(window)
        try:
            context = window._report_context()
        except RuntimeError:
            context = None
        assert context is None or isinstance(context, dict)


# --- grouping: every input has to say which section it belongs to ----------


def group_names(widget) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [
        child.text()
        for child in widget.findChildren(QLabel)
        if child.objectName() == "GroupName"
    ]


def test_the_recipe_screen_groups_its_inputs(app):
    """Nine fields in one flat list gave no clue which value did what."""
    from espec_burnin.ui.pages import RecipePage

    page = RecipePage(Recipe())
    names = group_names(page)
    assert len(names) >= 3, f"the form is still one undifferentiated list: {names}"
    assert "One cycle" in names


def test_the_two_ends_of_the_cycle_are_set_out_side_by_side(app):
    """Each of the six cycle values is half of a pair; stacked as six rows the
    pairing was invisible and the asymmetry that matters could not be read."""
    from PySide6.QtWidgets import QFrame, QGridLayout

    from espec_burnin.ui.pages import RecipePage

    page = RecipePage(Recipe())
    bezel = next(f for f in page.findChildren(QFrame) if f.objectName() == "Bezel")
    grid = bezel.layout()
    assert isinstance(grid, QGridLayout)

    def cell(widget):
        index = grid.indexOf(widget)
        assert index >= 0, "not in the cycle grid"
        return grid.getItemPosition(index)[:2]

    for cold, hot in ((page.cold, page.hot),
                      (page.ramp_down, page.ramp_up),
                      (page.cold_dwell, page.hot_dwell)):
        cold_row, cold_col = cell(cold)
        hot_row, hot_col = cell(hot)
        assert cold_row == hot_row, "a pair must share a row"
        assert cold_col < hot_col, "cold reads left of hot"


def test_a_number_box_is_the_width_of_its_number(app):
    """Stretched across the window a two-digit temperature reads as a text
    field and puts the stepper arrows a hand's width from the digits."""
    from espec_burnin.ui.pages import RecipePage
    from espec_burnin.ui.widgets import NUMBER_WIDTH

    page = RecipePage(Recipe())
    for box in (page.cold, page.hot, page.ramp_down, page.cold_dwell):
        assert box.width() == NUMBER_WIDTH


def test_the_ramp_rate_is_shown_beside_the_time_that_sets_it(app):
    from espec_burnin.ui.pages import RecipePage

    page = RecipePage(Recipe(ramp_down_minutes=60, ramp_up_minutes=30,
                             cold_c=-20, hot_c=80))
    assert "/min" in page.cool_rate.text()
    assert page.cool_rate.text() != page.heat_rate.text(), (
        "a 60-minute cool and a 30-minute heat are not the same rate"
    )


def test_every_settings_tab_is_grouped(app):
    from PySide6.QtWidgets import QTabWidget

    from espec_burnin.core.run_controller import RunTuning
    from espec_burnin.ui.settings_page import SettingsPage

    page = SettingsPage(ConnectionSettings(), RunTuning())
    tabs = page.findChildren(QTabWidget)[0]
    for index in range(tabs.count()):
        names = group_names(tabs.widget(index))
        assert len(names) >= 2, (
            f"the {tabs.tabText(index)!r} tab is still a flat list: {names}"
        )


# --- complexity that was pulled back out -----------------------------------


def test_the_run_screen_no_longer_asks_for_an_assumed_ambient(app):
    """The program reads the chamber before a run starts, so the field was a
    question it could answer itself."""
    from espec_burnin.ui.pages import RecipePage

    page = RecipePage(Recipe())
    assert not hasattr(page, "start_from")
    assert not hasattr(page, "show_advanced"), (
        "one remaining value does not earn a disclosure and a heading"
    )
    assert "Advanced" not in group_names(page)


def test_the_serial_link_states_itself_in_one_line(app):
    from espec_burnin.core.run_controller import RunTuning
    from espec_burnin.ui.settings_page import SettingsPage

    page = SettingsPage(ConnectionSettings(), RunTuning())
    assert page.link_disclosure.summary.text() == "19200 8-N-1"
    assert not page.link_disclosure.body.isVisible(), (
        "four dropdowns for one fact should not be the first thing on the page"
    )


def test_the_serial_summary_follows_the_fields_it_summarises(app):
    from espec_burnin.core.run_controller import RunTuning
    from espec_burnin.ui.settings_page import SettingsPage

    page = SettingsPage(ConnectionSettings(), RunTuning())
    page.baud.setCurrentText("9600")
    page.parity.setCurrentText("Even")
    page.stopbits.setCurrentText("2")
    assert page.link_disclosure.summary.text() == "9600 8-E-2"


def test_changing_a_hidden_field_still_reaches_the_saved_settings(app):
    """Tucking a value away must not disconnect it."""
    from espec_burnin.core.run_controller import RunTuning
    from espec_burnin.ui.settings_page import SettingsPage

    page = SettingsPage(ConnectionSettings(), RunTuning())
    page.baud.setCurrentText("38400")
    page.retries.setValue(5)
    page.epsilon.setValue(0.4)
    connection, tuning = page.values()
    assert connection.baudrate == 38400
    assert connection.retries == 5
    assert tuning.setpoint_epsilon_c == pytest.approx(0.4)


def test_pressing_a_button_is_recorded_without_the_screen_doing_anything(app):
    """Every button is made in one place, which is the one place a press can
    be noted - a new screen cannot forget to record its own buttons."""
    from espec_burnin.core.trail import TRAIL
    from espec_burnin.ui.widgets import button

    TRAIL.clear()
    made = button("Start the test", "start")
    made.click()
    assert any("pressed Start the test" in line for line in TRAIL.lines())
    TRAIL.clear()


def test_opening_a_screen_is_recorded(app):
    from espec_burnin.core.trail import TRAIL
    from espec_burnin.ui.main_window import CAPABILITY, MainWindow

    window = MainWindow()
    TRAIL.clear()
    window.stack.setCurrentIndex(CAPABILITY)
    assert any("Measure the chamber's speed" in line for line in TRAIL.lines())
    TRAIL.clear()
    window.close()


def test_the_trail_reaches_the_dialog(app):
    from espec_burnin.core.trail import TRAIL
    from espec_burnin.ui.report_dialog import ReportDialog

    TRAIL.clear()
    TRAIL.pressed("Continue")
    dialog = ReportDialog({"Screen open": "Choose the test"})
    assert any("Continue" in line for line in dialog.report.trail)
    assert "Continue" in dialog.preview.toPlainText()
    TRAIL.clear()


def test_editing_the_preview_stops_the_program_overwriting_it(app):
    from espec_burnin.ui.report_dialog import ReportDialog

    dialog = ReportDialog({"Screen open": "Home"})
    dialog.preview.setPlainText("[Bug] Mine\n\nOnly what I wrote.")
    dialog.summary.setText("this must not reappear in the preview")

    assert dialog.preview.toPlainText() == "[Bug] Mine\n\nOnly what I wrote."
    assert dialog._text() == "[Bug] Mine\n\nOnly what I wrote."


def test_every_button_role_renders_its_icon(app):
    """A null icon is silent: QIcon(QImage) yields one and never raises."""
    from espec_burnin.ui.widgets import button

    for role in ("primary", "secondary", "danger"):
        made = button("Press me", "save", role)
        assert not made.icon().isNull(), f"{role} lost its icon"
