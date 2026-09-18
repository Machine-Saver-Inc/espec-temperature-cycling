"""The run state machine.

Deliberately free of Qt so it can be tested headlessly and driven at a
time-scale far above real time.  The UI runs one of these on a worker thread
and listens to the callbacks.

Every threshold is a field on ``RunTuning`` rather than a module constant, so
all of it is editable in the program.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum

from espec_burnin.core.profile import (
    Phase,
    ProfilePoint,
    Recipe,
    is_dwell,
    setpoint_at,
)
from espec_burnin.core.recorder import Recorder, Sample
from espec_burnin.hardware.errors import ChamberError, NoReplyError

log = logging.getLogger(__name__)


@dataclass
class RunTuning:
    """How the run behaves. All of it editable under Settings."""

    sample_interval_s: float = 1.0
    setpoint_epsilon_c: float = 0.1   # do not rewrite for trivial changes
    comms_grace_minutes: float = 15.0  # give up on a run after this much silence
    runaway_delta_c: float = 15.0
    runaway_for_minutes: float = 10.0
    # Hard software clamp. Widening it is behind a confirmation in the UI.
    absolute_min_c: float = -25.0
    absolute_max_c: float = 85.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RunTuning:
        fields = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (data or {}).items() if k in fields})


class RunState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMMS_LOST = "comms_lost"
    FINISHED = "finished"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class Status:
    state: RunState
    point: ProfilePoint
    measured_c: float | None
    elapsed_s: float
    remaining_s: float
    comms_ok: bool
    message: str
    error: ChamberError | None = None


class RunController:
    def __init__(
        self,
        driver,
        recipe: Recipe,
        recorder: Recorder,
        tuning: RunTuning | None = None,
        *,
        on_status: Callable[[Status], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        resume_elapsed_s: float = 0.0,
        resume_offset_s: float = 0.0,
    ) -> None:
        self.driver = driver
        self.recipe = recipe
        self.recorder = recorder
        self.tuning = tuning or RunTuning()
        self.on_status = on_status or (lambda status: None)
        self.clock = clock
        self.sleep = sleep

        self.state = RunState.IDLE
        self._stop = threading.Event()
        self._started_at = 0.0
        self._resume_elapsed = resume_elapsed_s
        # Time withheld from the profile while the chamber was out of tolerance
        # during a dwell. This is what makes guaranteed soak work.
        self._soak_offset_s = resume_offset_s
        self._last_written_setpoint: float | None = None
        self._comms_lost_since: float | None = None
        self._runaway_since: float | None = None
        self._last_error: ChamberError | None = None

    # -- public API ----------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()

    @property
    def elapsed_s(self) -> float:
        return self._resume_elapsed + (self.clock() - self._started_at)

    @property
    def effective_elapsed_s(self) -> float:
        return max(0.0, self.elapsed_s - self._soak_offset_s)

    def run(self) -> RunState:
        self.state = RunState.RUNNING
        self._started_at = self.clock()
        last_tick = self.clock()
        grace_s = self.tuning.comms_grace_minutes * 60.0

        while not self._stop.is_set():
            now = self.clock()
            dt = now - last_tick
            last_tick = now

            point = setpoint_at(self.recipe, self.effective_elapsed_s)
            if point.phase is Phase.FINISHED:
                self._finish(RunState.FINISHED)
                return self.state

            measured, comms_ok = self._read()
            self._apply_soak_hold(point, measured, comms_ok, dt)

            if comms_ok:
                self._comms_lost_since = None
                self._last_error = None
                self._write_setpoint(point.setpoint_c)
                if self._is_runaway(point, measured, now):
                    self._finish(
                        RunState.FAILED, "the temperature is not following the setpoint"
                    )
                    return self.state
                self.state = RunState.RUNNING
            else:
                if self._comms_lost_since is None:
                    self._comms_lost_since = now
                self.state = RunState.COMMS_LOST
                if now - self._comms_lost_since >= grace_s:
                    reason = (
                        self._last_error.headline
                        if self._last_error
                        else "no reply from the chamber"
                    )
                    self._finish(RunState.FAILED, reason)
                    return self.state

            self._record(point, measured, comms_ok)
            self._emit(point, measured, comms_ok)
            self.sleep(self.tuning.sample_interval_s)

        self._finish(RunState.STOPPED)
        return self.state

    # -- internals -----------------------------------------------------------
    def _read(self) -> tuple[float | None, bool]:
        try:
            return self.driver.read_temperature(), True
        except ChamberError as exc:
            self._last_error = exc
            log.warning("read failed: %s", exc)
            return None, False
        except Exception as exc:  # noqa: BLE001 - any failure is a comms failure
            self._last_error = NoReplyError(str(exc))
            log.warning("read failed: %s", exc)
            return None, False

    def _write_setpoint(self, celsius: float) -> None:
        clamped = max(
            self.tuning.absolute_min_c, min(self.tuning.absolute_max_c, celsius)
        )
        if (
            self._last_written_setpoint is not None
            and abs(clamped - self._last_written_setpoint) < self.tuning.setpoint_epsilon_c
        ):
            return
        try:
            self.driver.write_setpoint(clamped)
            self._last_written_setpoint = clamped
        except Exception as exc:  # noqa: BLE001 - reported through comms state
            log.warning("setpoint write failed: %s", exc)

    def _apply_soak_hold(self, point, measured, comms_ok, dt) -> None:
        """Withhold profile time while a dwell is not actually being achieved."""
        if not self.recipe.guaranteed_soak or not is_dwell(point.phase):
            return
        out_of_tolerance = (
            not comms_ok
            or measured is None
            or abs(measured - point.setpoint_c) > self.recipe.tolerance_c
        )
        if out_of_tolerance:
            self._soak_offset_s += dt

    def _is_runaway(self, point, measured, now) -> bool:
        if measured is None or not is_dwell(point.phase):
            self._runaway_since = None
            return False
        if abs(measured - point.setpoint_c) > self.tuning.runaway_delta_c:
            if self._runaway_since is None:
                self._runaway_since = now
            return now - self._runaway_since >= self.tuning.runaway_for_minutes * 60.0
        self._runaway_since = None
        return False

    def _record(self, point, measured, comms_ok) -> None:
        self.recorder.record(
            Sample(
                timestamp=datetime.now(),
                elapsed_s=self.elapsed_s,
                cycle=point.cycle,
                phase=point.phase,
                setpoint_c=point.setpoint_c,
                measured_c=measured,
                comms_ok=comms_ok,
            )
        )
        self.recorder.write_state(
            status="running", elapsed_s=self.elapsed_s, offset_s=self._soak_offset_s
        )

    def _emit(self, point, measured, comms_ok, message: str = "") -> None:
        remaining = max(0.0, self.recipe.total_seconds - self.effective_elapsed_s)
        if not message:
            if not comms_ok:
                message = (
                    self._last_error.headline
                    if self._last_error
                    else "Not getting a temperature from the chamber"
                )
            elif measured is not None:
                message = (
                    f"{point.phase.label} — {measured:.1f} °C, "
                    f"heading for {point.setpoint_c:.1f} °C"
                )
        self.on_status(
            Status(
                state=self.state,
                point=point,
                measured_c=measured,
                elapsed_s=self.elapsed_s,
                remaining_s=remaining,
                comms_ok=comms_ok,
                message=message,
                error=None if comms_ok else self._last_error,
            )
        )

    def _finish(self, state: RunState, reason: str = "") -> None:
        """Always return the chamber to ambient, whatever ended the run."""
        self.state = state
        try:
            self.driver.write_setpoint(self.recipe.idle_c)
        except Exception as exc:  # noqa: BLE001 - nothing left to do about it
            log.warning("could not return the chamber to idle: %s", exc)
        self.recorder.close(
            status=state.value, elapsed_s=self.elapsed_s, offset_s=self._soak_offset_s
        )
        point = setpoint_at(self.recipe, self.effective_elapsed_s)
        self._emit(point, None, True, reason or state.value)
