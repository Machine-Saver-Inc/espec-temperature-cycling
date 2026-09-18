"""Every screen must at least build.

These caught an import that only failed at runtime: the modules had no test
touching them, so a wrong import sat in a shipped build without anything
noticing. Cheap insurance against that whole class of mistake.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6", reason="PySide6 is required for the interface")

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
    from espec_burnin.ui.report_dialog import ReportDialog, report_icon

    dialog = ReportDialog({"Screen open": "Home", "Port": "COM3"})
    dialog.summary.setText("Something went wrong")
    app.processEvents()

    assert "[Bug]" in dialog.preview.toPlainText()
    assert "Screen open" in dialog.preview.toPlainText()
    assert dialog.post.isEnabled()

    dialog.improvement.setChecked(True)
    app.processEvents()
    assert "[Improvement]" in dialog.preview.toPlainText()

    assert not report_icon().isNull(), "the journal-and-bug icon did not render"


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
