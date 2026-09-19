"""How fast the chamber actually moved, band by band.

Issue #3 handed us a stopped run and the question "where is it slowing down
and stalling?". The answer was not in the report: it showed the coldest
temperature reached and nothing about the shape of getting there. Averaged
over a whole ramp the chamber looked merely slow; split into five-degree
bands it was holding about 2.6 C/min for most of the descent and then
collapsing to 0.2 C/min over the last five degrees, which is a different
problem with a different cause.

Qt-free so it can be tested against a recorded run with no interface.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

BAND_C = 5.0
# Below this a band holds too little time to give a meaningful rate; a couple
# of samples either side of a boundary would otherwise read as a wild rate.
MIN_BAND_MINUTES = 0.2
# A gap longer than this is a stall in the data, not in the chamber: comms
# dropped, or the run was paused. Counting it would invent slow bands.
MAX_SAMPLE_GAP_S = 30.0
# A band this much slower than the run of bands before it is where it stalls.
STALL_RATIO = 0.4
# How far the chamber has to turn back before we call one descent (or climb)
# finished. Smaller than any real reversal, larger than the wobble of a
# controller holding a dwell.
REBOUND_C = 2.0
# A stretch of travel this short is a controller hunting around a setpoint, not
# the chamber going anywhere. Without this, a 40-minute dwell drifting a tenth
# of a degree became the slowest "band" in the table and outranked the ramps.
MIN_TRAVEL_C = 10.0
# A stretch is trimmed to the part where the chamber was actually moving: the
# flat lead-in while it still sat at the previous setpoint, and the settle at
# the far end once it had effectively arrived, are dwell and belong to neither
# band. Left in, a twenty-minute soak landed in one band and made the first row
# of every table the slowest.
PLATEAU_C = 0.5
# If more than this proportion of the range is slow, the chamber is not
# stalling at the end - it is simply slower than its own median, which happens
# whenever a run descends from two different starting temperatures.
MAX_STALL_SHARE = 0.4
# Running out of capacity happens over the last few degrees, not over a third
# of the range. Anything wider is a difference in commanded rate between
# cycles, and calling that a stall points the fault at the chamber.
MAX_STALL_BANDS = 3


@dataclass(frozen=True)
class Band:
    """One five-degree slice of temperature and how long the chamber took over it."""

    low_c: float
    high_c: float
    minutes: float

    @property
    def c_per_min(self) -> float:
        return (self.high_c - self.low_c) / self.minutes if self.minutes else 0.0

    @property
    def label(self) -> str:
        return f"{self.low_c:+.0f} to {self.high_c:+.0f} °C"

    @property
    def phrase(self) -> str:
        """The same band inside a sentence, where "+5" reads as a typo."""
        return f"between {self.low_c:.0f} and {self.high_c:.0f} °C"


@dataclass(frozen=True)
class Pace:
    """One direction of travel through the temperature range."""

    direction: str                 # "cooling" or "heating"
    bands: tuple[Band, ...]
    reached_c: float | None        # the furthest the chamber actually got
    target_c: float | None         # what it was told to reach

    @property
    def typical_c_per_min(self) -> float:
        """The rate over the bands that were not the stall.

        The median rather than the mean: one very slow band at the end would
        drag a mean down and make a healthy chamber look uniformly sluggish.
        """
        rates = sorted(abs(b.c_per_min) for b in self.bands)
        if not rates:
            return 0.0
        middle = len(rates) // 2
        if len(rates) % 2:
            return rates[middle]
        return (rates[middle - 1] + rates[middle]) / 2

    @property
    def stall(self) -> Band | None:
        """Where the chamber gave up, as one span, if it gave up at all.

        Taken from the end of travel inwards, because that is where a chamber
        runs out of capacity. The crawl often covers more than one band - the
        last ten degrees rather than the last five - and reporting only the
        final band would understate how much of the range is affected, so the
        whole trailing run of slow bands is merged into one.
        """
        if len(self.bands) < 3:
            return None
        typical = self.typical_c_per_min
        if typical <= 0:
            return None
        limit = typical * STALL_RATIO

        slow = 0
        for band in reversed(self.bands):
            if abs(band.c_per_min) > limit:
                break
            slow += 1
        if not slow or slow > len(self.bands) * MAX_STALL_SHARE:
            return None
        slow = min(slow, MAX_STALL_BANDS)

        tail = self.bands[-slow:]
        return Band(
            low_c=min(b.low_c for b in tail),
            high_c=max(b.high_c for b in tail),
            minutes=sum(b.minutes for b in tail),
        )

    @property
    def stalled_bands(self) -> tuple[Band, ...]:
        """The individual bands the stall covers, for marking up a table."""
        span = self.stall
        if span is None:
            return ()
        return tuple(
            b for b in self.bands if b.low_c >= span.low_c and b.high_c <= span.high_c
        )

    @property
    def short_by_c(self) -> float | None:
        """How far from the commanded extreme it stopped, if it fell short."""
        if self.reached_c is None or self.target_c is None:
            return None
        gap = (self.reached_c - self.target_c) if self.direction == "cooling" \
            else (self.target_c - self.reached_c)
        return gap if gap > 0.5 else None


def _travels(samples: Sequence, direction: str) -> list[list]:
    """Split a run into the stretches where it was travelling one way.

    A twelve-cycle run descends twelve times, so this cannot simply take the
    coldest point of the whole file. A stretch ends when the chamber turns
    back on itself by more than REBOUND_C, and it ends at the extreme it
    reached, not at the turning point: the minutes after that belong to the
    dwell, not to getting there.
    """
    cooling = direction == "cooling"
    readable = [s for s in samples if s.measured_c is not None]
    out: list[list] = []
    current: list = []
    extreme_value: float | None = None
    extreme_at = 0

    for sample in readable:
        value = sample.measured_c
        if not current:
            current, extreme_value, extreme_at = [sample], value, 0
            continue

        better = value <= extreme_value if cooling else value >= extreme_value
        current.append(sample)
        if better:
            extreme_value, extreme_at = value, len(current) - 1
            continue

        turned_back = abs(value - extreme_value) > REBOUND_C
        if turned_back:
            if extreme_at > 0:
                out.append(current[: extreme_at + 1])
            current, extreme_value, extreme_at = [sample], value, 0

    if current and extreme_at > 0:
        out.append(current[: extreme_at + 1])

    trimmed = (_trim_plateaus(stretch) for stretch in out)
    return [
        stretch for stretch in trimmed
        if len(stretch) > 1
        and abs(stretch[-1].measured_c - stretch[0].measured_c) >= MIN_TRAVEL_C
    ]


def _trim_plateaus(stretch: list) -> list:
    """Cut a stretch down to the part where the chamber was moving."""
    if len(stretch) < 3:
        return stretch
    start_value = stretch[0].measured_c
    first = 0
    for index, sample in enumerate(stretch):
        if abs(sample.measured_c - start_value) < PLATEAU_C:
            first = index
        else:
            break

    end_value = stretch[-1].measured_c
    last = len(stretch) - 1
    for index in range(len(stretch) - 1, -1, -1):
        if abs(stretch[index].measured_c - end_value) < PLATEAU_C:
            last = index
        else:
            break
    return stretch[first : last + 1] if last > first else stretch


def _pairs(samples: Sequence, direction: str):
    """Consecutive samples within one stretch of travel.

    A pair that has not moved at all still counts. The F4 reports tenths of a
    degree, so a chamber crawling at 0.2 C/min reports the same reading for
    several seconds together; dropping those pairs would shorten precisely the
    slow bands this module exists to find.
    """
    for stretch in _travels(samples, direction):
        for first, second in zip(stretch, stretch[1:], strict=False):
            seconds = second.elapsed_s - first.elapsed_s
            if not 0 < seconds <= MAX_SAMPLE_GAP_S:
                continue
            if direction == "cooling" and second.measured_c > first.measured_c:
                continue
            if direction == "heating" and second.measured_c < first.measured_c:
                continue
            yield first, second, seconds


def bands_for(samples: Sequence, direction: str, step: float = BAND_C) -> tuple[Band, ...]:
    """Minutes spent in each band, counting only travel in the given direction.

    Time is attributed by the midpoint of each pair of samples, which is
    accurate enough at one sample a second and avoids splitting intervals
    across band boundaries.
    """
    if direction not in ("cooling", "heating"):
        raise ValueError(f"direction must be cooling or heating, not {direction!r}")

    minutes: dict[int, float] = {}
    for first, second, seconds in _pairs(samples, direction):
        midpoint = (first.measured_c + second.measured_c) / 2
        index = int(midpoint // step)
        minutes[index] = minutes.get(index, 0.0) + seconds / 60.0

    ordered = sorted(minutes.items(), reverse=(direction == "cooling"))
    return tuple(
        Band(low_c=index * step, high_c=(index + 1) * step, minutes=held)
        for index, held in ordered
        if held >= MIN_BAND_MINUTES
    )


def pace_for(samples: Sequence, direction: str, target_c: float | None = None) -> Pace:
    measured = [s.measured_c for s in samples if s.measured_c is not None]
    reached = None
    if measured:
        reached = min(measured) if direction == "cooling" else max(measured)
    return Pace(
        direction=direction,
        bands=bands_for(samples, direction),
        reached_c=reached,
        target_c=target_c,
    )


def describe(pace: Pace) -> str:
    """One sentence a person at the chamber can act on."""
    if not pace.bands:
        return f"Not enough {pace.direction} data to judge the chamber's pace."

    verb = "cooled" if pace.direction == "cooling" else "heated"
    typical = pace.typical_c_per_min
    parts = [f"The chamber {verb} at about {typical:.1f} °C per minute"]

    stall = pace.stall
    if stall is not None:
        parts.append(
            f", then slowed to {abs(stall.c_per_min):.2f} °C per minute "
            f"{stall.phrase}, where it spent {stall.minutes:.0f} minutes"
        )

    short = pace.short_by_c
    if short is not None and pace.reached_c is not None:
        parts.append(
            f". It stopped at {pace.reached_c:.1f} °C, {short:.1f} °C short of "
            f"the {pace.target_c:.0f} °C it was asked for"
        )
    elif pace.reached_c is not None:
        parts.append(f". It reached {pace.reached_c:.1f} °C")
    parts.append(".")
    return "".join(parts)


def both_directions(samples: Iterable, cold_c: float, hot_c: float) -> tuple[Pace, Pace]:
    ordered = list(samples)
    return (
        pace_for(ordered, "cooling", cold_c),
        pace_for(ordered, "heating", hot_c),
    )
