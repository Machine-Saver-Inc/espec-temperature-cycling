"""Run output: the CSV log, the resumable state file, and the HTML report."""

from __future__ import annotations

import csv
import json
import platform
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from espec_burnin import __version__
from espec_burnin.core.profile import Phase, Recipe, is_dwell

CSV_COLUMNS = [
    "timestamp",
    "elapsed_s",
    "cycle",
    "phase",
    "setpoint_c",
    "measured_c",
    "comms_ok",
]


def results_root() -> Path:
    return Path.home() / "Documents" / "Espec Burn-In"


def safe_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _.-]", "", text).strip()
    return cleaned or "run"


@dataclass
class Sample:
    timestamp: datetime
    elapsed_s: float
    cycle: int
    phase: Phase
    setpoint_c: float
    measured_c: float | None
    comms_ok: bool


@dataclass
class CommsGap:
    start: datetime
    end: datetime | None = None

    @property
    def seconds(self) -> float:
        return ((self.end or self.start) - self.start).total_seconds()


@dataclass
class Recorder:
    """Owns one run's folder.

    The CSV is appended and flushed every sample rather than held in memory, so
    a power cut costs at most one second of data.
    """

    batch: str
    operator: str
    recipe: Recipe
    port: str
    adapter_serial: str | None = None
    started_at: datetime = field(default_factory=datetime.now)

    folder: Path = field(init=False)
    _csv_handle: object = field(init=False, default=None)
    _csv_writer: object = field(init=False, default=None)

    min_c: float | None = field(init=False, default=None)
    max_c: float | None = field(init=False, default=None)
    gaps: list[CommsGap] = field(init=False, default_factory=list)
    dwell_in_tolerance_s: float = field(init=False, default=0.0)
    dwell_total_s: float = field(init=False, default=0.0)
    cycles_completed: int = field(init=False, default=0)
    samples: list[Sample] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        stamp = self.started_at.strftime("%Y-%m-%d %H%M")
        self.folder = results_root() / f"{safe_name(self.batch)} {stamp}"
        self.folder.mkdir(parents=True, exist_ok=True)

        new_file = not (self.folder / "run.csv").exists()
        self._csv_handle = (self.folder / "run.csv").open("a", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._csv_handle)
        if new_file:
            self._csv_writer.writerow(CSV_COLUMNS)
            self._csv_handle.flush()
        self.write_state(status="running", elapsed_s=0.0, offset_s=0.0)

    # -- sampling ------------------------------------------------------------
    def record(self, sample: Sample) -> None:
        self._csv_writer.writerow(
            [
                sample.timestamp.isoformat(timespec="seconds"),
                round(sample.elapsed_s, 1),
                sample.cycle,
                sample.phase.value,
                round(sample.setpoint_c, 1),
                "" if sample.measured_c is None else round(sample.measured_c, 1),
                1 if sample.comms_ok else 0,
            ]
        )
        self._csv_handle.flush()
        self.samples.append(sample)

        if sample.comms_ok and sample.measured_c is not None:
            self.min_c = sample.measured_c if self.min_c is None else min(self.min_c, sample.measured_c)
            self.max_c = sample.measured_c if self.max_c is None else max(self.max_c, sample.measured_c)
            if self.gaps and self.gaps[-1].end is None:
                self.gaps[-1].end = sample.timestamp
            if is_dwell(sample.phase):
                self.dwell_total_s += 1.0
                if abs(sample.measured_c - sample.setpoint_c) <= self.recipe.tolerance_c:
                    self.dwell_in_tolerance_s += 1.0
        else:
            if not self.gaps or self.gaps[-1].end is not None:
                self.gaps.append(CommsGap(start=sample.timestamp))

        self.cycles_completed = max(self.cycles_completed, sample.cycle - 1)

    # -- state ---------------------------------------------------------------
    def write_state(self, *, status: str, elapsed_s: float, offset_s: float) -> None:
        """Rewritten every sample; this is what makes resume possible."""
        payload = {
            "app_version": __version__,
            "platform": platform.platform(),
            "batch": self.batch,
            "operator": self.operator,
            "port": self.port,
            "adapter_serial": self.adapter_serial,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "status": status,
            "elapsed_s": round(elapsed_s, 1),
            "soak_offset_s": round(offset_s, 1),
            "recipe": self.recipe.to_dict(),
        }
        tmp = self.folder / "run.json.tmp"
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.folder / "run.json")

    @staticmethod
    def load_state(folder: Path) -> dict | None:
        try:
            return json.loads((folder / "run.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def find_resumable() -> tuple[Path, dict] | None:
        """The most recent run still marked running whose end time has not passed."""
        root = results_root()
        if not root.is_dir():
            return None
        candidates = []
        for folder in root.iterdir():
            if not folder.is_dir():
                continue
            state = Recorder.load_state(folder)
            if not state or state.get("status") != "running":
                continue
            try:
                started = datetime.fromisoformat(state["started_at"])
                recipe = Recipe.from_dict(state["recipe"])
            except (KeyError, ValueError):
                continue
            # allow generous slack for guaranteed soak stretching the run
            if datetime.now() > started + timedelta(seconds=recipe.total_seconds * 2):
                continue
            candidates.append((started, folder, state))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        _, folder, state = candidates[0]
        return folder, state

    # -- finishing -----------------------------------------------------------
    def close(self, *, status: str, elapsed_s: float, offset_s: float) -> Path:
        # A run that reached the end of the profile completed its last cycle;
        # sample-derived counting can only ever see cycle N in progress.
        if status == "finished":
            self.cycles_completed = self.recipe.cycles
        self.write_state(status=status, elapsed_s=elapsed_s, offset_s=offset_s)
        try:
            self._csv_handle.flush()
            self._csv_handle.close()
        except Exception:  # noqa: BLE001 - closing is best effort
            pass
        return self.write_report(status=status, elapsed_s=elapsed_s)

    def verdict(self, status: str) -> str:
        total = self.recipe.cycles
        if status == "finished" and self.cycles_completed >= total:
            if self.dwell_total_s and self.dwell_in_tolerance_s / self.dwell_total_s >= 0.95:
                return f"{total} of {total} cycles completed within tolerance"
            return f"{total} of {total} cycles completed — dwell tolerance not met, see below"
        return f"{self.cycles_completed} of {total} cycles completed — run {status}"

    def write_report(self, *, status: str, elapsed_s: float) -> Path:
        from espec_burnin.core.report import render_report

        path = self.folder / "report.html"
        path.write_text(
            render_report(self, status=status, elapsed_s=elapsed_s), encoding="utf-8"
        )
        return path
