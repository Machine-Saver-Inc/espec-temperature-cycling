"""Main window: wires the screens together and owns the run."""

from __future__ import annotations

import logging
import webbrowser
from datetime import datetime

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from espec_burnin import APP_NAME, __version__
from espec_burnin.core.capability import CapabilityTest
from espec_burnin.core.profile import Recipe, format_duration
from espec_burnin.core.recorder import Recorder, results_root
from espec_burnin.core.run_controller import RunController, RunState
from espec_burnin.hardware.errors import ChamberError
from espec_burnin.hardware.f4 import WatlowF4
from espec_burnin.ui import settings as settings_mod
from espec_burnin.ui.capability_page import CapabilityPage, CapabilityWorker
from espec_burnin.ui.keepawake import KeepAwake
from espec_burnin.ui.pages import ConnectPage, HomePage, RecipePage, describe_error
from espec_burnin.ui.run_page import RunPage, RunWorker
from espec_burnin.ui.settings_page import SettingsPage
from espec_burnin.update.checker import (
    RELEASES_PAGE,
    CheckOutcome,
    Release,
    check_for_update_detailed,
    outcome_kind,
)
from espec_burnin.update.installer import (
    Applied,
    UpdateError,
    apply_update,
    download_asset,
    relaunch,
    verify_download,
)

log = logging.getLogger(__name__)

HOME, CONNECT, RECIPE, RUN, SETTINGS, CAPABILITY = range(6)


class UpdateWorker(QThread):
    """Reports what the check established, not just the happy case."""

    done = Signal(object)          # CheckOutcome

    def run(self) -> None:
        self.done.emit(check_for_update_detailed())


class DownloadWorker(QThread):
    """Fetch and verify an update off the GUI thread."""

    progress = Signal(int, int)
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, release: Release) -> None:
        super().__init__()
        self.release = release
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        def report(done: int, total: int) -> None:
            if self._cancelled:
                raise UpdateError("cancelled")
            self.progress.emit(done, total)

        try:
            path = download_asset(self.release, progress=report)
            verify_download(path, self.release)
        except UpdateError as exc:
            if not self._cancelled:
                self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.failed.emit(str(exc))
            return
        self.ready.emit(path)


class UpdateBanner(QFrame):
    update_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Banner")
        self.hide()
        self._release: Release | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        self.label = QLabel("")
        layout.addWidget(self.label)
        layout.addStretch(1)

        notes = QPushButton("What's new")
        notes.clicked.connect(self._show_notes)
        layout.addWidget(notes)

        update = QPushButton("Update now")
        update.clicked.connect(self._open_release)
        layout.addWidget(update)

        later = QPushButton("Later")
        later.clicked.connect(self.hide)
        layout.addWidget(later)

    def offer(self, release: Release) -> None:
        self._release = release
        self.label.setText(f"Version {release.version} is available.")
        self.show()

    def _show_notes(self) -> None:
        if self._release:
            QMessageBox.information(
                self, f"What's new in {self._release.version}",
                self._release.notes or "No release notes were provided.",
            )

    def _open_release(self) -> None:
        if self._release:
            self.update_requested.emit(self._release)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(940, 720)

        self.settings = settings_mod.load()
        self.connection = settings_mod.connection_from(self.settings)
        self.tuning = settings_mod.tuning_from(self.settings)
        self.port = None
        self.driver: WatlowF4 | None = None
        self.worker: RunWorker | None = None
        self.recorder: Recorder | None = None
        self.keep_awake = KeepAwake()
        self._pending_release: Release | None = None

        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.banner = UpdateBanner()
        self.banner.update_requested.connect(self._download_update)
        outer.addWidget(self.banner)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(container)

        self.home = HomePage()
        self.home.start_requested.connect(self._start_flow)
        self.home.results_requested.connect(self._open_results_folder)
        self.home.settings_requested.connect(self._open_settings)
        self.home.capability_requested.connect(self._open_capability)
        self.home.check_now_requested.connect(self._check_now)
        self.home.set_version_line(
            __version__,
            self.settings.get("last_update_check"),
            failed=self.settings.get("last_update_check_failed", False),
        )
        self.stack.addWidget(self.home)

        self.connect_page = ConnectPage(self.connection)
        self.connect_page.connected.connect(self._on_connected)
        self.connect_page.back.connect(lambda: self.stack.setCurrentIndex(HOME))
        self.stack.addWidget(self.connect_page)

        self.recipe_page = RecipePage(
            settings_mod.recipe_from(self.settings),
            self.settings.get("operator", ""),
        )
        self.recipe_page.start.connect(self._confirm_and_start)
        self.recipe_page.back.connect(lambda: self.stack.setCurrentIndex(HOME))
        self.stack.addWidget(self.recipe_page)

        self.run_page = RunPage()
        self.run_page.stop_requested.connect(self._stop_run)
        self.run_page.change_port_requested.connect(
            lambda: self.stack.setCurrentIndex(CONNECT)
        )
        self.stack.addWidget(self.run_page)

        self.settings_page = SettingsPage(self.connection, self.tuning)
        self.settings_page.saved.connect(self._on_settings_saved)
        self.settings_page.back.connect(lambda: self.stack.setCurrentIndex(HOME))
        self.stack.addWidget(self.settings_page)

        self.capability_page = CapabilityPage(self.tuning)
        self.capability_page.back.connect(lambda: self.stack.setCurrentIndex(HOME))
        self.capability_page.start_requested.connect(self._start_capability)
        self.capability_page.finished.connect(self._capability_finished)
        self.capability_page.stop_button.clicked.connect(self._stop_capability)
        self.stack.addWidget(self.capability_page)
        self.capability_worker: CapabilityWorker | None = None

        QTimer.singleShot(400, self._reconnect_remembered_adapter)
        QTimer.singleShot(1200, self._check_for_updates)
        QTimer.singleShot(800, self._offer_resume)

    # -- connection ----------------------------------------------------------
    def _reconnect_remembered_adapter(self) -> None:
        from espec_burnin.hardware.ports import find_port_by_serial_number, probe_port

        serial_number = self.settings.get("adapter_serial")
        port = find_port_by_serial_number(serial_number) if serial_number else None
        if port is None:
            self.home.set_connection("No chamber connected yet.", False)
            return
        temperature = probe_port(port.device)
        if temperature is None:
            self.home.set_connection(
                f"Adapter found on {port.device}, but the chamber did not answer.", False
            )
            return
        self.port = port
        self.home.set_connection(
            f"Chamber connected on {port.device} — currently {temperature:.1f} °C.",
            True,
        )

    def _start_flow(self) -> None:
        self.stack.setCurrentIndex(RECIPE if self.port else CONNECT)

    def _on_connected(self, port) -> None:
        self.port = port
        self.settings["adapter_serial"] = port.serial_number
        self.settings["last_port"] = port.device
        settings_mod.save(self.settings)
        self.stack.setCurrentIndex(RECIPE)

    # -- the run -------------------------------------------------------------
    def _confirm_and_start(self, recipe: Recipe, batch: str, operator: str) -> None:
        if self.port is None:
            self.stack.setCurrentIndex(CONNECT)
            return

        answer = QMessageBox.question(
            self,
            "Start the burn-in?",
            f"<b>{batch}</b> — {recipe.cycles} cycles between {recipe.cold_c:g} °C "
            f"and {recipe.hot_c:g} °C, about "
            f"{format_duration(recipe.total_seconds)}.<br><br>"
            "The chamber will begin cooling toward "
            f"{recipe.cold_c:g} °C immediately.<br><br>"
            "This computer must stay on for the whole run.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return

        self.settings["recipe"] = recipe.to_dict()
        self.settings["operator"] = operator
        settings_mod.save(self.settings)
        self._launch(recipe, batch, operator)

    def _launch(self, recipe, batch, operator, resume_elapsed=0.0, resume_offset=0.0) -> None:
        try:
            self.driver = WatlowF4(self.port.device, self.connection)
            self.recorder = Recorder(
                batch=batch,
                operator=operator,
                recipe=recipe,
                port=self.port.device,
                adapter_serial=self.port.serial_number,
            )
        except ChamberError as exc:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle("Could not start the run")
            box.setText(exc.headline)
            box.setTextFormat(Qt.RichText)
            box.setInformativeText(describe_error(exc))
            box.exec()
            self.stack.setCurrentIndex(CONNECT)
            return
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            QMessageBox.critical(self, "Could not start the run", str(exc))
            return

        controller = RunController(
            self.driver,
            recipe,
            self.recorder,
            self.tuning,
            resume_elapsed_s=resume_elapsed,
            resume_offset_s=resume_offset,
        )
        self.worker = RunWorker(controller)
        self.worker.status.connect(self.run_page.update_status, Qt.QueuedConnection)
        self.worker.done.connect(self._on_run_finished, Qt.QueuedConnection)

        self.run_page.begin(batch, self.port.device, recipe.cycles)
        self.stack.setCurrentIndex(RUN)
        self.banner.hide()          # never offer an update mid-run
        self.keep_awake.start()
        self.worker.start()

    def _stop_run(self) -> None:
        if self.worker is None:
            return
        answer = QMessageBox.question(
            self,
            "Stop the run?",
            "The chamber will be returned to room temperature and the results kept.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer == QMessageBox.Yes:
            self.worker.stop()

    def _on_run_finished(self, state: RunState) -> None:
        self.keep_awake.stop()
        if self.driver is not None:
            self.driver.close()
            self.driver = None

        folder = self.recorder.folder if self.recorder else results_root()
        verdict = self.recorder.verdict(state.value) if self.recorder else state.value

        box = QMessageBox(self)
        box.setWindowTitle("Run finished" if state is RunState.FINISHED else "Run ended")
        box.setText(verdict)
        box.setInformativeText(f"Results are in {folder}")
        open_report = box.addButton("Open report", QMessageBox.AcceptRole)
        box.addButton("Close", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_report:
            webbrowser.open((folder / "report.html").as_uri())

        self.worker = None
        self.recorder = None
        self.stack.setCurrentIndex(HOME)
        self._reconnect_remembered_adapter()
        if self._pending_release is not None:
            self.banner.offer(self._pending_release)

    # -- resume --------------------------------------------------------------
    def _offer_resume(self) -> None:
        found = Recorder.find_resumable()
        if not found or self.port is None:
            return
        folder, state = found
        answer = QMessageBox.question(
            self,
            "Resume the interrupted run?",
            f"A burn-in of batch <b>{state.get('batch')}</b> was in progress "
            f"({format_duration(state.get('elapsed_s', 0))} elapsed).<br><br>Resume it?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        self._launch(
            Recipe.from_dict(state["recipe"]),
            state.get("batch", "resumed"),
            state.get("operator", ""),
            resume_elapsed=float(state.get("elapsed_s", 0.0)),
            resume_offset=float(state.get("soak_offset_s", 0.0)),
        )

    # -- misc ----------------------------------------------------------------
    def _check_for_updates(self) -> None:
        if not self.settings.get("check_for_updates", True):
            return
        self._update_worker = UpdateWorker()
        self._update_worker.done.connect(self._on_check_done, Qt.QueuedConnection)
        self._update_worker.start()

    def _on_check_done(self, outcome: CheckOutcome, announce: bool = False) -> None:
        """One place that decides what a check meant."""
        self._last_check_failed = not outcome.reached_github
        self._record_check(ok=outcome.reached_github)

        kind = outcome_kind(outcome)
        if kind == "update":
            self._pending_release = outcome.release
            if self.worker is None:          # never interrupt a run
                self.banner.offer(outcome.release)
            return

        if not announce:
            return

        if kind == "current":
            QMessageBox.information(
                self, "Up to date",
                f"Version {__version__} is the newest release.",
            )
            return

        # Never claim to be up to date on the strength of a failed request.
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Could not check for updates")
        box.setText("The program could not reach GitHub, so it does not know "
                    "whether a newer version exists.")
        box.setInformativeText(outcome.error or "")
        open_page = box.addButton("Open the releases page", QMessageBox.ActionRole)
        box.addButton("Close", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_page:
            webbrowser.open(RELEASES_PAGE)

    def _record_check(self, ok: bool = True) -> None:
        stamp = datetime.now().strftime("%d %b %Y %H:%M")
        if ok:
            self.settings["last_update_check"] = stamp
            self.settings["last_update_check_failed"] = False
        else:
            self.settings["last_update_check_failed"] = True
        settings_mod.save(self.settings)
        self.home.set_version_line(
            __version__,
            self.settings.get("last_update_check"),
            failed=not ok,
        )

    def _check_now(self) -> None:
        """Manual check, for anyone who wants to ask rather than wait."""
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self, "A run is in progress",
                "Updates are not offered while a burn-in is running.",
            )
            return
        self._manual_check = UpdateWorker()
        self._manual_check.done.connect(
            lambda outcome: self._on_check_done(outcome, announce=True),
            Qt.QueuedConnection,
        )
        self._manual_check.start()

    # -- doing the update ----------------------------------------------------
    def _download_update(self, release: Release) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self, "A run is in progress",
                "The update will be offered again when the burn-in finishes.",
            )
            return

        self._progress = QProgressDialog(
            f"Downloading version {release.version}\u2026", "Cancel", 0, 100, self
        )
        self._progress.setWindowTitle("Updating")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)

        self._download = DownloadWorker(release)
        self._download.progress.connect(self._on_download_progress, Qt.QueuedConnection)
        self._download.ready.connect(self._on_download_ready, Qt.QueuedConnection)
        self._download.failed.connect(self._on_download_failed, Qt.QueuedConnection)
        self._progress.canceled.connect(self._download.cancel)
        self._download.start()

    def _on_download_progress(self, done: int, total: int) -> None:
        if total:
            self._progress.setMaximum(100)
            self._progress.setValue(int(done * 100 / total))
            self._progress.setLabelText(
                f"Downloading\u2026 {done / 1048576:.0f} of {total / 1048576:.0f} MB"
            )
        else:
            self._progress.setMaximum(0)

    def _on_download_failed(self, message: str) -> None:
        self._progress.close()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("The update was not installed")
        box.setText(message)
        box.setInformativeText(
            "Nothing has been changed. You can download it by hand from the "
            "release page instead."
        )
        open_page = box.addButton("Open the release page", QMessageBox.ActionRole)
        box.addButton("Close", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_page and self._pending_release:
            webbrowser.open(self._pending_release.html_url)

    def _on_download_ready(self, path) -> None:
        self._progress.setLabelText("Verified. Installing\u2026")
        self._progress.setValue(100)
        try:
            result = apply_update(path)
        except UpdateError as exc:
            self._on_download_failed(str(exc))
            return
        self._progress.close()

        if result.outcome is Applied.MANUAL:
            QMessageBox.information(self, "Downloaded", result.message)
            return

        QMessageBox.information(self, "Updating", result.message)
        if result.outcome is Applied.RESTARTING:
            relaunch(result.path)
        self._updating = True
        self.close()

    def _open_settings(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self, "A run is in progress",
                "Settings cannot be changed while a burn-in is running.",
            )
            return
        self.stack.setCurrentIndex(SETTINGS)

    def _on_settings_saved(self, connection, tuning) -> None:
        self.connection = connection
        self.tuning = tuning
        self.settings["connection"] = connection.to_dict()
        self.settings["tuning"] = tuning.to_dict()
        settings_mod.save(self.settings)
        self.connect_page.settings = connection
        self.recipe_page.reload_profiles()
        self.stack.setCurrentIndex(HOME)
        self._reconnect_remembered_adapter()

    # -- chamber capability --------------------------------------------------
    def _open_capability(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self, "A run is in progress",
                "The chamber is busy with a burn-in. Wait until it finishes.",
            )
            return
        if self.port is None:
            self.stack.setCurrentIndex(CONNECT)
            return
        self.capability_page.reset()
        self.stack.setCurrentIndex(CAPABILITY)

    def _start_capability(self, settings, name, loaded, notes) -> None:
        if self.port is None:
            self.stack.setCurrentIndex(CONNECT)
            return
        if QMessageBox.question(
            self, "Start the measurement?",
            f"The chamber will be driven to {settings.cold_target_clamped:g} \u00b0C "
            f"and then {settings.hot_target_clamped:g} \u00b0C, and left to settle "
            f"at each end.\n\n"
            "This takes a few hours and this computer must stay on throughout.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Yes,
        ) != QMessageBox.Yes:
            return

        try:
            self.capability_driver = WatlowF4(self.port.device, self.connection)
        except ChamberError as exc:
            QMessageBox.critical(self, "Could not start", describe_error(exc))
            self.stack.setCurrentIndex(CONNECT)
            return

        test = CapabilityTest(
            self.capability_driver, name, settings, loaded=loaded, load_notes=notes
        )
        self.capability_worker = CapabilityWorker(test)
        self.capability_worker.progress.connect(
            self.capability_page.show_progress, Qt.QueuedConnection
        )
        self.capability_worker.done.connect(
            self._capability_measured, Qt.QueuedConnection
        )
        self.keep_awake.start()
        self.capability_worker.start()

    def _stop_capability(self) -> None:
        if self.capability_worker is None:
            return
        if QMessageBox.question(
            self, "Stop the measurement?",
            "The profile will be incomplete, and the chamber will be returned to "
            "room temperature.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        ) == QMessageBox.Yes:
            self.capability_worker.stop()

    def _capability_measured(self, profile) -> None:
        self.keep_awake.stop()
        if getattr(self, "capability_driver", None) is not None:
            self.capability_driver.close()
            self.capability_driver = None
        self.capability_worker = None
        self.capability_page.show_result(profile)

    def _capability_finished(self, profile) -> None:
        self.recipe_page.reload_profiles()
        self.stack.setCurrentIndex(HOME)

    def _open_results_folder(self) -> None:
        folder = results_root()
        folder.mkdir(parents=True, exist_ok=True)
        webbrowser.open(folder.as_uri())

    def closeEvent(self, event) -> None:
        if getattr(self, "_updating", False):
            self.keep_awake.stop()
            event.accept()
            return
        if self.worker is not None and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                "A run is in progress",
                "Closing now will stop the burn-in and return the chamber to room "
                "temperature. Close anyway?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.stop()
            self.worker.wait(5000)
        self.keep_awake.stop()
        event.accept()
