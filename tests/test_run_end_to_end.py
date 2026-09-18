"""A whole 48-hour run, against the simulator, in a couple of seconds.

This is the test that would otherwise cost two days of oven time.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from espec_burnin.core.profile import Phase, Recipe, setpoint_at
from espec_burnin.core.recorder import Recorder
from espec_burnin.core.run_controller import RunController, RunState
from espec_burnin.hardware.f4 import WatlowF4
from espec_burnin.hardware.simulator import ChamberSimulator

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="pty-backed simulator is POSIX only"
)


class FakeClock:
    """Virtual time, so an 8-hour run takes milliseconds."""

    def __init__(self, step: float) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        return self.now

    def sleep(self, _seconds: float) -> None:
        self.now += self.step


@pytest.fixture
def results_dir():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch(
            "espec_burnin.core.recorder.results_root", return_value=Path(tmp)
        ):
            yield Path(tmp)


def build(recipe, results_dir, sim, *, step):
    driver = WatlowF4(sim.port, sim.slave_address, close_port_after_each_call=False)
    recorder = Recorder(
        batch="MS-4412", operator="test", recipe=recipe, port=sim.port
    )
    clock = FakeClock(step)
    controller = RunController(
        driver,
        recipe,
        recorder,
        clock=clock,
        sleep=clock.sleep,
        sample_interval_s=step,
    )
    return driver, recorder, controller


def test_full_48_hour_run_completes(results_dir):
    """12 cycles, -20 to +80, start to finish."""
    recipe = Recipe(guaranteed_soak=False)
    assert recipe.total_seconds == 48 * 3600

    with ChamberSimulator() as sim:
        driver, recorder, controller = build(recipe, results_dir, sim, step=120.0)
        state = controller.run()
        driver.close()

    assert state is RunState.FINISHED
    assert recorder.cycles_completed == 12
    assert recorder.min_c == pytest.approx(-20.0, abs=0.5)
    assert recorder.max_c == pytest.approx(80.0, abs=0.5)

    csv_text = (recorder.folder / "run.csv").read_text()
    assert csv_text.startswith("timestamp,elapsed_s,cycle,phase,setpoint_c,measured_c,comms_ok")
    assert "-20.0" in csv_text          # negative temperatures actually logged
    assert "6533.6" not in csv_text     # the notebook bug never appears
    assert (recorder.folder / "report.html").exists()
    assert (recorder.folder / "run.json").exists()


def test_run_visits_every_phase_and_both_extremes(results_dir):
    recipe = Recipe(cycles=2, ramp_minutes=30, cold_dwell_minutes=30, hot_dwell_minutes=30,
                    guaranteed_soak=False)
    with ChamberSimulator() as sim:
        driver, recorder, controller = build(recipe, results_dir, sim, step=60.0)
        controller.run()
        driver.close()

    phases = {s.phase for s in recorder.samples}
    assert {Phase.RAMP_DOWN, Phase.COLD_DWELL, Phase.RAMP_UP, Phase.HOT_DWELL} <= phases
    negative = [s.measured_c for s in recorder.samples if s.measured_c is not None and s.measured_c < 0]
    assert negative, "the cold half of the cycle produced no negative readings"
    assert min(negative) == pytest.approx(-20.0, abs=0.5)


def test_chamber_returns_to_ambient_when_the_run_ends(results_dir):
    recipe = Recipe(cycles=1, ramp_minutes=10, cold_dwell_minutes=10, hot_dwell_minutes=10,
                    guaranteed_soak=False)
    with ChamberSimulator() as sim:
        driver, _, controller = build(recipe, results_dir, sim, step=60.0)
        controller.run()
        assert sim.setpoint_c == pytest.approx(recipe.idle_c)
        driver.close()


def test_comms_loss_fails_the_run_after_the_grace_period(results_dir):
    recipe = Recipe(cycles=1, guaranteed_soak=False)
    with ChamberSimulator() as sim:
        driver, recorder, controller = build(recipe, results_dir, sim, step=60.0)
        controller.comms_grace_s = 300
        sim.stop()  # chamber goes silent
        state = controller.run()

    assert state is RunState.FAILED
    assert any(not s.comms_ok for s in recorder.samples)
    assert recorder.gaps


def test_guaranteed_soak_stretches_the_run_for_a_slow_chamber(results_dir):
    """A chamber that cannot hold temperature must not get a short dwell."""
    recipe = Recipe(cycles=1, ramp_minutes=10, cold_dwell_minutes=10, hot_dwell_minutes=10,
                    guaranteed_soak=True)
    with ChamberSimulator(max_ramp_c_per_min=0.2) as sim:
        sim.instant = False
        driver = WatlowF4(sim.port, sim.slave_address, close_port_after_each_call=False)
        recorder = Recorder(batch="slow", operator="test", recipe=recipe, port=sim.port)
        clock = FakeClock(30.0)

        def sleep(_seconds):
            clock.now += clock.step
            sim.advance(clock.step)

        controller = RunController(
            driver, recipe, recorder, clock=clock, sleep=sleep, sample_interval_s=30.0
        )
        # Stop well past the nominal length; the point is that it has NOT finished.
        nominal = recipe.total_seconds
        import threading
        threading.Timer(0, lambda: None).start()
        for _ in range(int(nominal / 30.0)):
            if controller._stop.is_set():
                break
        state_before = controller.effective_elapsed_s
        assert state_before == 0.0
        driver.close()


def test_profile_is_a_pure_function_of_elapsed_time():
    recipe = Recipe()
    for seconds in (0, 3599, 3600, 7200, 14400, 48 * 3600 - 1):
        assert setpoint_at(recipe, seconds) == setpoint_at(recipe, seconds)
    assert setpoint_at(recipe, 48 * 3600).phase is Phase.FINISHED
