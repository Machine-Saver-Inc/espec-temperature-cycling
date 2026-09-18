"""The chamber capability test.

Whether a commanded ramp is achievable depends on the load and on how much heat
leaks through the cable entry ports, so it has to be measured. These tests drive
the measurement against a simulated chamber whose real rates are known, and
check the profile recovers them.
"""

from __future__ import annotations

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
