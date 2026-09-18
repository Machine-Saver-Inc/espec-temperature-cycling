"""The chamber capability test.

Whether a commanded ramp is achievable depends on the load and on how much heat
leaks through the cable entry ports, so it has to be measured. These tests drive
the measurement against a simulated chamber whose real rates are known, and
check the profile recovers them.
"""

from __future__ import annotations

import csv
import json
import sys

import pytest

from espec_burnin.core.capability import (
    CapabilitySettings,
    CapabilityTest,
    ChamberProfile,
    Direction,
    bin_for,
)
from espec_burnin.hardware.f4 import ConnectionSettings, WatlowF4
from espec_burnin.hardware.simulator import ChamberSimulator

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the pty-backed simulator is POSIX only"
)


class SimClock:
    """Virtual time that also advances the simulated chamber."""

    def __init__(self, sim, step: float) -> None:
        self.sim = sim
        self.step = step
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, _seconds: float) -> None:
        self.now += self.step
        self.sim.advance(self.step)


def measure(sim, **kwargs) -> ChamberProfile:
    driver = WatlowF4(sim.port, ConnectionSettings(
        slave_address=sim.slave_address, close_port_after_each_call=False))
    clock = SimClock(sim, 30.0)
    settings = CapabilitySettings(
        sample_interval_s=30.0, slope_window_s=120.0, plateau_minutes=5.0,
        timeout_minutes=600.0, **kwargs)
    test = CapabilityTest(driver, "bench", settings, clock=clock, sleep=clock.sleep)
    profile = test.run()
    driver.close()
    return profile


def test_measured_rates_match_the_chamber(tmp_path):
    """A chamber that heats at 3 and cools at 1 must be measured as such."""
    with ChamberSimulator(start_temp_c=25.0, max_ramp_c_per_min=3.0,
                          max_cool_c_per_min=1.0) as sim:
        sim.instant = False
        profile = measure(sim)

    assert profile.cooling_rates and profile.heating_rates
    cooling = profile.rate_at(0.0, Direction.COOLING)
    heating = profile.rate_at(0.0, Direction.HEATING)
    assert cooling == pytest.approx(1.0, rel=0.15)
    assert heating == pytest.approx(3.0, rel=0.15)
    assert cooling < heating


def test_traversal_time_follows_the_measured_rate():
    with ChamberSimulator(start_temp_c=25.0, max_ramp_c_per_min=2.0,
                          max_cool_c_per_min=1.0) as sim:
        sim.instant = False
        profile = measure(sim)

    # 100 degC at about 1 degC/min cooling is about 100 minutes.
    cooling = profile.minutes_to_traverse(80.0, -20.0)
    heating = profile.minutes_to_traverse(-20.0, 80.0)
    assert cooling == pytest.approx(100, rel=0.2)
    assert heating == pytest.approx(50, rel=0.2)
    assert profile.recommended_minutes(80.0, -20.0) > cooling   # includes headroom


def test_a_chamber_that_cannot_reach_target_is_recorded_as_such():
    """Heat leaking through the cable ports is exactly this case."""
    with ChamberSimulator(start_temp_c=25.0, max_ramp_c_per_min=3.0,
                          max_cool_c_per_min=2.0, floor_c=-14.0) as sim:
        sim.instant = False
        profile = measure(sim, cold_target_c=-25.0, hot_target_c=60.0)

    assert profile.reachable_min_c == pytest.approx(-14.0, abs=1.0)
    assert not profile.can_reach(-20.0)
    assert profile.can_reach(-10.0)


def test_rate_is_integrated_per_band_not_averaged():
    """Most of the time is spent in the slow bands; an average hides that."""
    profile = ChamberProfile(
        cooling_rates={str(bin_for(t)): rate for t, rate in
                       [(70, 3.0), (50, 3.0), (30, 3.0), (10, 2.0),
                        (-5, 1.0), (-15, 0.25)]}
    )
    banded = profile.minutes_to_traverse(75.0, -20.0)
    naive_average = (75.0 - -20.0) / (sum([3, 3, 3, 2, 1, 0.25]) / 6)
    assert banded > naive_average * 1.5, "banded integration must not flatter the chamber"


def test_bands_are_five_degrees_wide():
    assert bin_for(0.0) == 2.5
    assert bin_for(4.9) == 2.5
    assert bin_for(5.0) == 7.5
    assert bin_for(-0.1) == -2.5
    assert bin_for(-20.0) == -17.5


def test_a_profile_survives_saving_and_loading():
    original = ChamberProfile(name="loaded", loaded=True, load_notes="12 boards",
                              cooling_rates={"2.5": 1.4}, reachable_min_c=-18.0)
    restored = ChamberProfile.from_dict(original.to_dict())
    assert restored.name == "loaded"
    assert restored.load_notes == "12 boards"
    assert restored.rate_at(0.0, Direction.COOLING) == pytest.approx(1.4)
    assert restored.reachable_min_c == -18.0


def test_an_unmeasured_direction_says_so_rather_than_guessing():
    profile = ChamberProfile(cooling_rates={"2.5": 1.0})
    assert profile.minutes_to_traverse(-20.0, 80.0) is None
    assert profile.rate_at(0.0, Direction.HEATING) is None


# --- issue #1: the capability test drove past the safety clamp --------------
# The setup screen offered -40 degC and +105 degC while the run clamp was
# -25/+85, and the test wrote setpoints straight to the driver, so measuring
# the chamber was a way around the limits every run obeys.

class RecordingDriver:
    """Captures every setpoint commanded, so the clamp can be asserted."""

    def __init__(self, temperature: float = 25.0) -> None:
        self.temperature = temperature
        self.commanded: list[float] = []

    def read_temperature(self, retries: int | None = None) -> float:
        return self.temperature

    def write_setpoint(self, celsius: float, retries: int | None = None) -> None:
        self.commanded.append(celsius)


def test_the_measurement_never_commands_past_the_safety_clamp():
    driver = RecordingDriver()
    settings = CapabilitySettings(
        cold_target_c=-40.0, hot_target_c=105.0,     # what the user typed
        absolute_min_c=-25.0, absolute_max_c=85.0,   # what the limits allow
        sample_interval_s=1.0, plateau_minutes=0.05, slope_window_s=2.0,
        timeout_minutes=1.0,
    )

    class Clock:
        now = 0.0

        def __call__(self):
            return self.now

        def sleep(self, _s):
            self.now += 30.0

    clock = Clock()
    CapabilityTest(driver, "clamped", settings, clock=clock, sleep=clock.sleep).run()

    assert driver.commanded, "the test commanded nothing at all"
    assert min(driver.commanded) >= -25.0, f"commanded {min(driver.commanded)} degC"
    assert max(driver.commanded) <= 85.0, f"commanded {max(driver.commanded)} degC"
    assert -40.0 not in driver.commanded
    assert 105.0 not in driver.commanded


def test_the_clamp_is_reported_so_the_confirmation_can_be_honest():
    settings = CapabilitySettings(
        cold_target_c=-40.0, hot_target_c=105.0,
        absolute_min_c=-25.0, absolute_max_c=85.0,
    )
    assert settings.cold_target_clamped == -25.0
    assert settings.hot_target_clamped == 85.0
    assert settings.targets_were_limited


def test_targets_inside_the_limits_are_left_alone():
    settings = CapabilitySettings(
        cold_target_c=-20.0, hot_target_c=80.0,
        absolute_min_c=-25.0, absolute_max_c=85.0,
    )
    assert settings.cold_target_clamped == -20.0
    assert settings.hot_target_clamped == 80.0
    assert not settings.targets_were_limited


def test_widening_the_limits_widens_what_the_measurement_may_command():
    """The clamp is the control, not a hard-coded ceiling."""
    settings = CapabilitySettings(
        cold_target_c=-40.0, hot_target_c=105.0,
        absolute_min_c=-45.0, absolute_max_c=110.0,
    )
    assert settings.cold_target_clamped == -40.0
    assert settings.hot_target_clamped == 105.0


# --- the measurement must survive being stopped -----------------------------
# A speed test runs for hours and is exactly the thing that stalls. Keeping its
# samples in memory meant stopping it threw away the evidence of the stall.

def test_every_sample_is_on_disk_before_the_test_finishes(tmp_path):
    """Written and flushed as it goes, not gathered up at the end."""
    from espec_burnin.core.capability import CapabilityLog

    driver = RecordingDriver(temperature=25.0)
    log = CapabilityLog("Espec BTZ-133 - Serial 0612223", "Loaded", root=tmp_path)
    settings = CapabilitySettings(
        cold_target_c=-25.0, hot_target_c=85.0,
        sample_interval_s=1.0, slope_window_s=180.0,
        plateau_minutes=5.0, timeout_minutes=60.0,
    )

    class Clock:
        now = 0.0

        def __call__(self):
            return self.now

        def sleep(self, _s):
            self.now += 30.0
            driver.temperature -= 1.0      # a chamber that keeps cooling

    clock = Clock()
    test = CapabilityTest(driver, "Loaded", settings, log=log,
                          clock=clock, sleep=clock.sleep)
    test.run()

    csv_path = log.folder / "measurement.csv"
    assert csv_path.exists()
    rows = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert rows[0].startswith("timestamp,elapsed_s,direction,target_c,measured_c")
    assert len(rows) > 5, "the samples were not written as they happened"
    assert (log.folder / "profile.json").exists()


def test_a_stalled_chamber_is_visible_in_the_log(tmp_path):
    """A stall is a run of samples that counted toward no band."""
    from espec_burnin.core.capability import CapabilityLog

    driver = RecordingDriver(temperature=25.0)
    log = CapabilityLog("Espec BTZ-133", "Stalling", root=tmp_path)
    settings = CapabilitySettings(
        cold_target_c=-40.0, hot_target_c=85.0,
        absolute_min_c=-40.0, absolute_max_c=85.0,
        sample_interval_s=1.0, slope_window_s=180.0,
        plateau_minutes=3.0, timeout_minutes=60.0,
    )

    class Clock:
        now = 0.0
        ticks = 0

        def __call__(self):
            return self.now

        def sleep(self, _s):
            self.now += 30.0
            self.ticks += 1
            # Cools for a while, then stops moving: the stall.
            if self.ticks < 8:
                driver.temperature -= 2.0

    clock = Clock()
    CapabilityTest(driver, "Stalling", settings, log=log,
                   clock=clock, sleep=clock.sleep).run()

    rows = list(csv.DictReader((log.folder / "measurement.csv").open(encoding="utf-8")))
    assert rows
    counted = [r for r in rows if r["counted"] == "1"]
    stalled = [r for r in rows if r["counted"] == "0"]
    assert counted, "nothing was recorded while the chamber was actually cooling"
    assert stalled, "the stall left no trace in the log"

    # The coldest band still making progress is where it gave up.
    coldest_moving = min(float(r["measured_c"]) for r in counted)
    assert coldest_moving > -40.0


def test_the_log_records_the_rate_so_the_slowdown_can_be_plotted(tmp_path):
    from espec_burnin.core.capability import CapabilityLog

    driver = RecordingDriver(temperature=25.0)
    log = CapabilityLog("Chamber", "Rates", root=tmp_path)
    settings = CapabilitySettings(
        sample_interval_s=1.0, slope_window_s=180.0,
        plateau_minutes=5.0, timeout_minutes=60.0,
    )

    class Clock:
        now = 0.0

        def __call__(self):
            return self.now

        def sleep(self, _s):
            self.now += 30.0
            driver.temperature -= 1.5

    clock = Clock()
    CapabilityTest(driver, "Rates", settings, log=log,
                   clock=clock, sleep=clock.sleep).run()

    rows = list(csv.DictReader((log.folder / "measurement.csv").open(encoding="utf-8")))
    with_rate = [r for r in rows if r["rate_c_per_min"]]
    assert with_rate, "no rate was ever recorded"
    assert all(r["band_c"] for r in rows), "every sample must carry its band"
    assert {r["direction"] for r in rows} <= {"cooling", "heating"}


def test_stopping_early_still_leaves_a_usable_file(tmp_path):
    from espec_burnin.core.capability import CapabilityLog

    driver = RecordingDriver(temperature=25.0)
    log = CapabilityLog("Chamber", "Stopped", root=tmp_path)
    settings = CapabilitySettings(sample_interval_s=1.0, slope_window_s=180.0,
                                  plateau_minutes=5.0, timeout_minutes=60.0)

    class Clock:
        now = 0.0
        ticks = 0

        def __call__(self):
            return self.now

        def sleep(self, _s):
            self.now += 30.0
            self.ticks += 1
            driver.temperature -= 1.0
            if self.ticks == 6:
                test.stop()          # the operator presses Stop

    clock = Clock()
    test = CapabilityTest(driver, "Stopped", settings, log=log,
                          clock=clock, sleep=clock.sleep)
    profile = test.run()

    assert profile.aborted
    rows = (log.folder / "measurement.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) >= 5, "stopping threw away the samples"
    saved = json.loads((log.folder / "profile.json").read_text(encoding="utf-8"))
    assert saved["aborted"] is True
