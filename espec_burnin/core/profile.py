"""The temperature profile: setpoint as a pure function of elapsed time.

Keeping this a pure function is what makes a communication gap survivable --
when the chamber answers again the program simply asks where the cycle should
be by now.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class Phase(str, Enum):
    RAMP_DOWN = "ramp_down"
    COLD_DWELL = "cold_dwell"
    RAMP_UP = "ramp_up"
    HOT_DWELL = "hot_dwell"
    FINISHED = "finished"

    @property
    def label(self) -> str:
        return {
            Phase.RAMP_DOWN: "Cooling",
            Phase.COLD_DWELL: "Holding cold",
            Phase.RAMP_UP: "Heating",
            Phase.HOT_DWELL: "Holding hot",
            Phase.FINISHED: "Finished",
        }[self]


@dataclass(frozen=True)
class Recipe:
    """A burn-in recipe.

    The default is 12 cycles of 4 hours, which is 48 hours exactly, ramping at
    1.67 degC/min -- comfortably inside what the chamber can hold.  A commanded
    ramp the chamber cannot follow becomes a step change, and the recorded
    profile stops meaning anything.
    """

    name: str = "Standard 48-hour PCB burn-in"
    cycles: int = 12
    cold_c: float = -20.0
    hot_c: float = 80.0
    ramp_minutes: float = 60.0
    cold_dwell_minutes: float = 60.0
    hot_dwell_minutes: float = 60.0
    tolerance_c: float = 2.0
    guaranteed_soak: bool = True
    idle_c: float = 25.0        # where the chamber is left when a run ends
    start_from_c: float = 25.0  # assumed ambient at the first ramp

    def __post_init__(self) -> None:
        if self.cycles < 1:
            raise ValueError("a run needs at least one cycle")
        if self.cold_c >= self.hot_c:
            raise ValueError("cold setpoint must be below hot setpoint")
        if min(self.ramp_minutes, self.cold_dwell_minutes, self.hot_dwell_minutes) <= 0:
            raise ValueError("ramp and dwell durations must be positive")

    @property
    def cycle_seconds(self) -> float:
        return (
            self.ramp_minutes
            + self.cold_dwell_minutes
            + self.ramp_minutes
            + self.hot_dwell_minutes
        ) * 60.0

    @property
    def total_seconds(self) -> float:
        return self.cycle_seconds * self.cycles

    @property
    def ramp_c_per_min(self) -> float:
        return (self.hot_c - self.cold_c) / self.ramp_minutes

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Recipe:
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})


@dataclass(frozen=True)
class ProfilePoint:
    setpoint_c: float
    cycle: int          # 1-based; 0 once finished
    phase: Phase
    phase_elapsed_s: float
    phase_total_s: float


def setpoint_at(recipe: Recipe, elapsed_s: float) -> ProfilePoint:
    """Where the profile should be after ``elapsed_s`` seconds of run time.

    ``elapsed_s`` is *effective* elapsed time: when guaranteed soak is on, the
    run controller withholds time while the chamber is out of tolerance, so
    a lagging chamber stretches the run rather than shortening the dwell.
    """
    if elapsed_s < 0:
        elapsed_s = 0.0
    if elapsed_s >= recipe.total_seconds:
        return ProfilePoint(recipe.idle_c, 0, Phase.FINISHED, 0.0, 0.0)

    cycle_index = int(elapsed_s // recipe.cycle_seconds)
    t = elapsed_s - cycle_index * recipe.cycle_seconds
    cycle = cycle_index + 1

    ramp_s = recipe.ramp_minutes * 60.0
    cold_s = recipe.cold_dwell_minutes * 60.0
    hot_s = recipe.hot_dwell_minutes * 60.0

    # The first ramp down starts from ambient; later ones start from the hot dwell.
    ramp_down_from = recipe.start_from_c if cycle_index == 0 else recipe.hot_c

    if t < ramp_s:
        fraction = t / ramp_s
        value = ramp_down_from + (recipe.cold_c - ramp_down_from) * fraction
        return ProfilePoint(round(value, 1), cycle, Phase.RAMP_DOWN, t, ramp_s)

    t -= ramp_s
    if t < cold_s:
        return ProfilePoint(recipe.cold_c, cycle, Phase.COLD_DWELL, t, cold_s)

    t -= cold_s
    if t < ramp_s:
        fraction = t / ramp_s
        value = recipe.cold_c + (recipe.hot_c - recipe.cold_c) * fraction
        return ProfilePoint(round(value, 1), cycle, Phase.RAMP_UP, t, ramp_s)

    t -= ramp_s
    return ProfilePoint(recipe.hot_c, cycle, Phase.HOT_DWELL, t, hot_s)


def is_dwell(phase: Phase) -> bool:
    return phase in (Phase.COLD_DWELL, Phase.HOT_DWELL)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"
