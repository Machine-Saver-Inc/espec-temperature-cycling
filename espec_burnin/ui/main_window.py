"""Main window: wires the screens together and owns the run."""

from __future__ import annotations

import logging
import webbrowser

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from espec_burnin import APP_NAME, __version__
from espec_burnin.core.profile import Recipe, format_duration
from espec_burnin.core.recorder import Recorder, results_root
from espec_burnin.core.run_controller import RunController, RunState
from espec_burnin.hardware.f4 import WatlowF4
from espec_burnin.ui import settings as settings_mod
from espec_burnin.ui.keepawake import KeepAwake
from espec_burnin.ui.pages import ConnectPage, HomePage, RecipePage
from espec_burnin.ui.run_page import RunPage, RunWorker
from espec_burnin.update.checker import Release, check_for_update

log = logging.getLogger(__name__)

HOME, CONNECT, RECIPE, RUN = range(4)


class UpdateWorker(QThread):
    available = Signal(object)

    def run(self) -> None:
        release = check_for_update()
        if release is not None:
            self.available.emit(release)


class UpdateBanner(QFrame):
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
            webbrowser.open(self._release.html_url)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(940, 720)

        self.settings = settings_mod.load()
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
        outer.addWidget(self.banner)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(container)

        self.home = HomePage()
        self.home.start_requested.connect(self._start_flow)
        self.home.results_requested.connect(self._open_results_folder)
        self.stack.addWidget(self.home)

        self.connect_page = ConnectPage()
        self.connect_page.connected.connect(self._on_connected)
        self.connect_page.back.connect(lambda: self.stack.setCurrentIndex(HOME))
        self.stack.addWidget(self.connect_page)

        self.recipe_page = RecipePage(
            Recipe.from_dict(self.settings.get("recipe", {})),
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
            self.driver = WatlowF4(self.port.device)
            self.recorder = Recorder(
                batch=batch,
                operator=operator,
                recipe=recipe,
                port=self.port.device,
                adapter_serial=self.port.serial_number,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            QMessageBox.critical(self, "Could not start", str(exc))
            return

        controller = RunController(
            self.driver,
            recipe,
            self.recorder,
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
        self._update_worker.available.connect(self._on_update_available)
        self._update_worker.start()

    def _on_update_available(self, release: Release) -> None:
        self._pending_release = release
        if self.worker is None:      # never interrupt a run
            self.banner.offer(release)

    def _open_results_folder(self) -> None:
        folder = results_root()
        folder.mkdir(parents=True, exist_ok=True)
        webbrowser.open(folder.as_uri())

    def closeEvent(self, event) -> None:
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
