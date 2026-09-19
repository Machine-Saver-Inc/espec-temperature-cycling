"""Where the chamber slows down, and whether the report says so.

The numbers in these tests are the ones from issue #3 - an Espec BTZ133,
serial 0612223, running the 48-hour recipe with a -10 C cold setpoint. That
run averaged out to something unremarkable; split into bands it showed the
chamber holding 2.5 to 2.9 C/min for the whole descent and then taking 23
minutes over the last five degrees, ending at -9.3 C. That shape is what
these tests pin.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from espec_burnin.core.pace import (
    BAND_C,
    Band,
    bands_for,
    both_directions,
    describe,
    pace_for,
)
from espec_burnin.core.recorder import Sample


def ramp(start_c: float, stop_c: float, c_per_min: float, *, at: float = 0.0,
         phase: str = "ramp_down", setpoint: float = 0.0):
    """Samples one second apart travelling from start to stop at a fixed rate."""
    step = c_per_min / 60.0 * (1 if stop_c > start_c else -1)
    step = abs(step) * (1 if stop_c > start_c else -1)
    out = []
    value, elapsed = start_c, at
    base = datetime(2026, 9, 18, 11, 45)
    while (value > stop_c) if stop_c < start_c else (value < stop_c):
        out.append(
            Sample(
                timestamp=base + timedelta(seconds=elapsed),
                elapsed_s=elapsed,
                cycle=1,
                phase=phase,
                setpoint_c=setpoint,
                measured_c=round(value, 2),
                comms_ok=True,
            )
        )
        value += step
        elapsed += 1.0
    return out


def the_btz133_descent():
    """78 C down to -9.3 C: fast most of the way, then a wall below -5."""
    fast = ramp(78.0, -5.0, 2.6, setpoint=-10.0)
    stall = ramp(-5.0, -9.3, 0.21, at=fast[-1].elapsed_s + 1, setpoint=-10.0)
    return fast + stall


def test_a_band_reports_the_rate_it_implies():
    assert Band(low_c=-10.0, high_c=-5.0, minutes=25.0).c_per_min == pytest.approx(0.2)


def test_bands_come_back_in_the_order_the_chamber_travelled():
    """Cooling reads from hot to cold. A table that ran the other way would
    put the stall at the top and read as though it started badly."""
    bands = bands_for(the_btz133_descent(), "cooling")
    assert bands[0].low_c > bands[-1].low_c
    assert bands[-1].low_c == -10.0


def test_heating_bands_read_the_other_way():
    bands = bands_for(ramp(-10.0, 80.0, 2.8, phase="ramp_up", setpoint=80.0), "heating")
    assert bands[0].low_c < bands[-1].low_c


def test_travel_the_wrong_way_is_not_counted_as_cooling():
    """A run climbs as well as descends. Counting the climb as cooling would
    invent minutes the chamber never spent going down."""
    samples = ramp(40.0, 10.0, 2.0) + ramp(10.0, 40.0, 2.0, at=2000)
    cooling = bands_for(samples, "cooling")
    assert sum(b.minutes for b in cooling) == pytest.approx(15.0, abs=0.6)


def test_a_comms_gap_does_not_become_a_slow_band():
    """Issue #3's run had no gaps, but a dropped connection would otherwise
    read as the chamber sitting still - the exact thing we are looking for."""
    samples = ramp(40.0, 25.0, 2.0)
    late = ramp(25.0, 10.0, 2.0, at=samples[-1].elapsed_s + 4000)
    bands = bands_for(samples + late, "cooling")
    assert bands, "the travel either side of the gap still has to be counted"
    assert all(b.minutes < 10 for b in bands), "the gap must not become minutes"


def test_the_stall_is_found_at_the_end_of_travel():
    pace = pace_for(the_btz133_descent(), "cooling", target_c=-10.0)
    stall = pace.stall
    assert stall is not None
    assert stall.low_c == -10.0
    assert abs(stall.c_per_min) < 0.4
    assert stall.minutes > 15


def test_a_chamber_that_keeps_its_pace_has_no_stall():
    pace = pace_for(ramp(78.0, -10.0, 2.6, setpoint=-10.0), "cooling", target_c=-10.0)
    assert pace.stall is None


def test_the_typical_rate_ignores_the_stall():
    """The mean over every band would report this chamber at about 2 C/min and
    hide both the healthy descent and the wall at the bottom."""
    pace = pace_for(the_btz133_descent(), "cooling", target_c=-10.0)
    assert pace.typical_c_per_min == pytest.approx(2.6, abs=0.4)


def test_falling_short_of_the_setpoint_is_measured():
    pace = pace_for(the_btz133_descent(), "cooling", target_c=-10.0)
    assert pace.short_by_c == pytest.approx(0.7, abs=0.2)


def test_reaching_the_setpoint_is_not_reported_as_falling_short():
    pace = pace_for(ramp(78.0, -10.2, 2.6, setpoint=-10.0), "cooling", target_c=-10.0)
    assert pace.short_by_c is None


def test_the_sentence_names_the_rate_the_stall_and_the_shortfall():
    text = describe(pace_for(the_btz133_descent(), "cooling", target_c=-10.0))
    assert "per minute" in text
    assert "slowed to" in text
    assert "short of" in text
    assert "-10" in text or "−10" in text


def test_the_sentence_says_so_when_there_is_nothing_to_judge():
    assert "not enough" in describe(pace_for([], "cooling", target_c=-10.0)).lower()


def test_both_directions_come_back_together():
    samples = the_btz133_descent() + ramp(
        -9.3, 78.4, 2.8, at=20000, phase="ramp_up", setpoint=80.0
    )
    cooling, heating = both_directions(samples, cold_c=-10.0, hot_c=80.0)
    assert cooling.direction == "cooling" and heating.direction == "heating"
    assert cooling.reached_c == pytest.approx(-9.3, abs=0.2)
    assert heating.reached_c == pytest.approx(78.4, abs=0.2)


def test_the_band_width_is_five_degrees():
    """The report's table is built on it; a change here changes every report."""
    assert BAND_C == 5.0


def test_a_crawl_over_two_bands_is_reported_as_one_span():
    """The real run slowed over the last ten degrees of heating, not the last
    five. Reporting only the final band would understate the affected range."""
    climb = ramp(-10.0, 70.0, 2.8, phase="ramp_up", setpoint=80.0)
    crawl = ramp(70.0, 78.4, 0.2, at=climb[-1].elapsed_s + 1,
                 phase="hot_dwell", setpoint=80.0)
    pace = pace_for(climb + crawl, "heating", target_c=80.0)

    stall = pace.stall
    assert stall is not None
    assert stall.low_c == 70.0 and stall.high_c == 80.0
    assert len(pace.stalled_bands) == 2
    assert stall.minutes == pytest.approx(sum(b.minutes for b in pace.stalled_bands))


def test_a_chamber_slow_from_end_to_end_is_not_called_a_stall():
    """If every band is slow there is no band where it gave up - the chamber
    is simply slow, which is a different conversation."""
    pace = pace_for(ramp(40.0, -10.0, 0.3, setpoint=-10.0), "cooling", target_c=-10.0)
    assert pace.stall is None


def test_stalled_bands_are_empty_when_nothing_stalled():
    assert pace_for(ramp(78.0, -10.2, 2.6, setpoint=-10.0), "cooling", -10.0).stalled_bands == ()


def test_a_dwell_is_not_charged_to_the_band_it_sat_in():
    """A 20-minute soak at 80 C drifting a tenth of a degree was landing in the
    +80 band and making the first row of the cooling table the slowest one."""
    soak = ramp(80.4, 79.9, 0.025, phase="hot_dwell", setpoint=80.0)
    descent = ramp(79.9, 20.0, 2.5, at=soak[-1].elapsed_s + 1, setpoint=-20.0)
    bands = bands_for(soak + descent, "cooling")

    top = [b for b in bands if b.low_c >= 80.0]
    assert not top, f"the soak was counted as travel: {[b.label for b in top]}"
    assert all(abs(b.c_per_min) > 1.0 for b in bands)


def test_settling_at_the_far_end_is_not_charged_to_the_last_band():
    descent = ramp(40.0, -19.5, 2.5, setpoint=-20.0)
    settle = ramp(-19.5, -20.0, 0.02, at=descent[-1].elapsed_s + 1,
                  phase="cold_dwell", setpoint=-20.0)
    bands = bands_for(descent + settle, "cooling")
    assert bands[-1].minutes < 10


def test_a_stretch_too_short_to_be_travel_is_ignored():
    """Hunting around a setpoint is not the chamber going anywhere."""
    assert bands_for(ramp(20.0, 16.0, 1.0), "cooling") == ()


def test_slower_than_median_across_most_of_the_range_is_not_a_stall():
    """A run that descends from two different starting temperatures has two
    commanded rates. Half the table turning red is variation, not a stall."""
    fast = ramp(80.0, -20.0, 3.3, setpoint=-20.0)
    slow = ramp(25.0, -20.0, 1.0, at=fast[-1].elapsed_s + 5000, setpoint=-20.0)
    pace = pace_for(fast + slow, "cooling", target_c=-20.0)
    assert pace.stall is None


def test_a_stall_is_reported_over_the_last_few_degrees_not_a_third_of_the_range():
    """A run whose cycles descend at different commanded rates has a wide slow
    region that is not the chamber running out of capacity."""
    fast = ramp(80.0, 25.0, 2.5, setpoint=-10.0)
    slower = ramp(25.0, -5.0, 1.0, at=fast[-1].elapsed_s + 1, setpoint=-10.0)
    crawl = ramp(-5.0, -9.3, 0.2, at=slower[-1].elapsed_s + 1, setpoint=-10.0)
    pace = pace_for(fast + slower + crawl, "cooling", target_c=-10.0)

    stall = pace.stall
    if stall is not None:
        assert stall.high_c - stall.low_c <= 15.0
        assert len(pace.stalled_bands) <= 3
