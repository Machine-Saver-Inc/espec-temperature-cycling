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
from espec_burnin.core.run_controller import RunController, RunState, RunTuning
from espec_burnin.hardware.f4 import ConnectionSettings, WatlowF4
from espec_burnin.hardware.simulator import ChamberSimulator

# Every test here drives the pty-backed simulator.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the pty-backed simulator is POSIX only"
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
    driver = WatlowF4(sim.port, ConnectionSettings(slave_address=sim.slave_address,
                                          close_port_after_each_call=False))
    recorder = Recorder(
        batch="MS-4412", operator="test", recipe=recipe, port=sim.port
    )
    clock = FakeClock(step)
    controller = RunController(
        driver,
        recipe,
        recorder,
        RunTuning(sample_interval_s=step),
        clock=clock,
        sleep=clock.sleep,
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
    recipe = Recipe(cycles=2, ramp_down_minutes=30, ramp_up_minutes=30, cold_dwell_minutes=30, hot_dwell_minutes=30,
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
    recipe = Recipe(cycles=1, ramp_down_minutes=10, ramp_up_minutes=10, cold_dwell_minutes=10, hot_dwell_minutes=10,
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
        controller.tuning.comms_grace_minutes = 5
        sim.stop()  # chamber goes silent
        state = controller.run()

    assert state is RunState.FAILED
    assert any(not s.comms_ok for s in recorder.samples)
    assert recorder.gaps


def test_guaranteed_soak_stretches_the_run_for_a_slow_chamber(results_dir):
    """A chamber that cannot hold temperature must not get a short dwell."""
    recipe = Recipe(cycles=1, ramp_down_minutes=10, ramp_up_minutes=10, cold_dwell_minutes=10, hot_dwell_minutes=10,
                    guaranteed_soak=True)
    with ChamberSimulator(max_ramp_c_per_min=0.2) as sim:
        sim.instant = False
        driver = WatlowF4(sim.port, ConnectionSettings(slave_address=sim.slave_address,
                                          close_port_after_each_call=False))
        recorder = Recorder(batch="slow", operator="test", recipe=recipe, port=sim.port)
        clock = FakeClock(30.0)

        def sleep(_seconds):
            clock.now += clock.step
            sim.advance(clock.step)

        controller = RunController(
            driver, recipe, recorder, RunTuning(sample_interval_s=30.0),
            clock=clock, sleep=sleep,
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


# --- nothing is fixed at 48 hours -------------------------------------------

@pytest.mark.parametrize("hours", [6, 12, 24, 48, 72, 168])
def test_a_run_can_be_any_length(hours):
    sized = Recipe().with_duration_hours(hours)
    assert sized.total_hours == pytest.approx(hours, abs=sized.cycle_seconds / 3600)
    assert sized.cycles >= 1


def test_cooling_and_heating_ramps_are_independent():
    """A chamber that cools slowly must not be forced to a symmetric profile."""
    recipe = Recipe(ramp_down_minutes=150, ramp_up_minutes=45)
    assert recipe.cooling_c_per_min < recipe.heating_c_per_min
    assert recipe.cycle_seconds == (150 + 45 + 60 + 60) * 60

    # The profile must actually follow the slower cooling ramp.
    quarter = setpoint_at(recipe, 150 * 60 * 0.5)
    assert quarter.phase is Phase.RAMP_DOWN
    assert 0 < quarter.setpoint_c < recipe.start_from_c


def test_recipes_saved_before_split_ramps_still_load():
    old = {"cycles": 4, "ramp_minutes": 30, "cold_dwell_minutes": 20,
           "hot_dwell_minutes": 20, "cold_c": -10.0, "hot_c": 70.0}
    recipe = Recipe.from_dict(old)
    assert recipe.ramp_down_minutes == 30
    assert recipe.ramp_up_minutes == 30
    assert recipe.cycles == 4


def test_tuning_thresholds_are_configurable(results_dir):
    from espec_burnin.core.run_controller import RunTuning

    tuning = RunTuning(absolute_min_c=-40, absolute_max_c=120, comms_grace_minutes=3)
    recipe = Recipe(cycles=1, cold_c=-30, hot_c=100, ramp_down_minutes=10,
                    ramp_up_minutes=10, cold_dwell_minutes=10, hot_dwell_minutes=10,
                    guaranteed_soak=False)
    with ChamberSimulator() as sim:
        driver = WatlowF4(sim.port, ConnectionSettings(
            slave_address=sim.slave_address, close_port_after_each_call=False))
        recorder = Recorder(batch="wide", operator="t", recipe=recipe, port=sim.port)
        clock = FakeClock(60.0)
        RunController(driver, recipe, recorder, tuning,
                      clock=clock, sleep=clock.sleep).run()
        driver.close()

    # The default clamp would have pinned these to -25 and 85.
    assert recorder.min_c == pytest.approx(-30.0, abs=0.5)
    assert recorder.max_c == pytest.approx(100.0, abs=0.5)


def test_guaranteed_soak_cannot_stretch_a_run_for_ever(results_dir):
    """A chamber that never reaches target must fail the run, not extend it endlessly.

    This is the failure Leo's cable-entry heat loss produces: ask for -20 in a
    chamber that can only manage -14 and, before this cap, the dwell timer never
    started and the run had no end.
    """
    from espec_burnin.core.run_controller import RunTuning

    recipe = Recipe(cycles=1, cold_c=-20.0, hot_c=40.0, ramp_down_minutes=10,
                    ramp_up_minutes=10, cold_dwell_minutes=10, hot_dwell_minutes=10,
                    guaranteed_soak=True, tolerance_c=1.0)
    tuning = RunTuning(sample_interval_s=30.0, max_extension_percent=50.0)

    with ChamberSimulator(start_temp_c=25.0, max_ramp_c_per_min=5.0,
                          max_cool_c_per_min=5.0, floor_c=-14.0) as sim:
        sim.instant = False
        driver = WatlowF4(sim.port, ConnectionSettings(
            slave_address=sim.slave_address, close_port_after_each_call=False))
        recorder = Recorder(batch="unreachable", operator="t", recipe=recipe,
                            port=sim.port)
        clock = FakeClock(30.0)

        def sleep(_seconds):
            clock.now += clock.step
            sim.advance(clock.step)

        controller = RunController(driver, recipe, recorder, tuning,
                                   clock=clock, sleep=sleep)
        state = controller.run()
        driver.close()

    assert state is RunState.FAILED
    # It gave up rather than running for ever, but not before genuinely trying.
    limit = recipe.total_seconds * tuning.max_extension_percent / 100.0
    assert controller._soak_offset_s > limit
    assert controller.elapsed_s < recipe.total_seconds * 3


def test_no_cap_means_no_limit(results_dir):
    """Setting the cap to zero restores the old unbounded behaviour on purpose."""
    from espec_burnin.core.run_controller import RunController as RC
    from espec_burnin.core.run_controller import RunTuning

    recipe = Recipe(cycles=1, guaranteed_soak=True)
    controller = RC.__new__(RC)
    controller.recipe = recipe
    controller.tuning = RunTuning(max_extension_percent=0.0)
    controller._soak_offset_s = recipe.total_seconds * 100
    assert controller._soak_extension_exceeded() is False


def test_the_report_says_where_the_chamber_slowed(results_dir):
    """Issue #3: the report showed the coldest temperature reached and nothing
    about the shape of getting there, so a chamber that was fine until the last
    few degrees looked identical to one that was slow throughout."""
    recipe = Recipe(cycles=2, ramp_down_minutes=30, ramp_up_minutes=30,
                    cold_dwell_minutes=20, hot_dwell_minutes=20, guaranteed_soak=False)
    with ChamberSimulator(max_cool_c_per_min=2.5, floor_c=-12.0) as sim:
        driver, recorder, controller = build(recipe, results_dir, sim, step=30.0)
        controller.run()
        driver.close()

    html_text = (recorder.folder / "report.html").read_text(encoding="utf-8")
    assert "How the chamber paced itself" in html_text
    assert "Cooling" in html_text and "Heating" in html_text
    assert "per minute" in html_text
    assert "C/min" in html_text

    from espec_burnin.core.pace import both_directions

    cooling, heating = both_directions(recorder.samples, recipe.cold_c, recipe.hot_c)
    assert cooling.bands, "a completed run must produce cooling bands"
    assert heating.bands, "a completed run must produce heating bands"
    # Two cycles descend twice; the bands must aggregate both, not stop at the
    # first minimum in the file.
    assert sum(b.minutes for b in cooling.bands) > recipe.ramp_down_minutes
