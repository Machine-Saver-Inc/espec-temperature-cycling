"""The temperature profile: setpoint as a pure function of elapsed time.

Keeping this a pure function is what makes a communication gap survivable --
when the chamber answers again the program simply asks where the cycle should
be by now.

Nothing here is fixed at 48 hours. The default preset happens to work out at
48, but every number is a field, and a run can be specified either as a number
of cycles or as a wall-clock duration.
"""

from __future__ import annotations

import math
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
    """A burn-in recipe. Every field is editable in the program.

    Cooling and heating get their own ramp times, because a chamber almost
    never cools as fast as it heats -- and with cable entry ports open, the
    difference gets larger.
    """

    name: str = "Standard 48-hour PCB burn-in"
    cycles: int = 12
    cold_c: float = -20.0
    hot_c: float = 80.0
    ramp_down_minutes: float = 60.0
    ramp_up_minutes: float = 60.0
    cold_dwell_minutes: float = 60.0
    hot_dwell_minutes: float = 60.0
    tolerance_c: float = 2.0
    guaranteed_soak: bool = True
    idle_c: float = 25.0         # where the chamber is left when a run ends
    start_from_c: float = 25.0   # assumed ambient at the first ramp

    def __post_init__(self) -> None:
        if self.cycles < 1:
            raise ValueError("a run needs at least one cycle")
        if self.cold_c >= self.hot_c:
            raise ValueError("the cold setpoint must be below the hot setpoint")
        durations = (
            self.ramp_down_minutes,
            self.ramp_up_minutes,
            self.cold_dwell_minutes,
            self.hot_dwell_minutes,
        )
        if min(durations) <= 0:
            raise ValueError("ramp and dwell durations must be greater than zero")
        if self.tolerance_c <= 0:
            raise ValueError("tolerance must be greater than zero")

    # -- derived ------------------------------------------------------------
    @property
    def cycle_seconds(self) -> float:
        return (
            self.ramp_down_minutes
            + self.cold_dwell_minutes
            + self.ramp_up_minutes
            + self.hot_dwell_minutes
        ) * 60.0

    @property
    def total_seconds(self) -> float:
        return self.cycle_seconds * self.cycles

    @property
    def total_hours(self) -> float:
        return self.total_seconds / 3600.0

    @property
    def cooling_c_per_min(self) -> float:
        return (self.hot_c - self.cold_c) / self.ramp_down_minutes

    @property
    def heating_c_per_min(self) -> float:
        return (self.hot_c - self.cold_c) / self.ramp_up_minutes

    def cycles_for_hours(self, hours: float) -> int:
        """How many whole cycles fit in a wall-clock duration (at least one)."""
        if hours <= 0:
            return 1
        return max(1, round(hours * 3600.0 / self.cycle_seconds))

    def with_duration_hours(self, hours: float) -> Recipe:
        """The same recipe sized to run for roughly ``hours``."""
        return self.replace(cycles=self.cycles_for_hours(hours))

    def replace(self, **changes) -> Recipe:
        data = self.to_dict()
        data.update(changes)
        return Recipe(**data)

    # -- serialisation ------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Recipe:
        data = dict(data or {})
        # Recipes saved before ramps were split carry a single ramp_minutes.
        if "ramp_minutes" in data:
            single = data.pop("ramp_minutes")
            data.setdefault("ramp_down_minutes", single)
            data.setdefault("ramp_up_minutes", single)
        fields = set(cls.__dataclass_fields__)
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

    ``elapsed_s`` is *effective* elapsed time: with guaranteed soak on, the run
    controller withholds time while the chamber is out of tolerance, so a
    lagging chamber stretches the run rather than shortening the dwell.
    """
    elapsed_s = max(0.0, elapsed_s)
    if elapsed_s >= recipe.total_seconds:
        return ProfilePoint(recipe.idle_c, 0, Phase.FINISHED, 0.0, 0.0)

    cycle_index = int(elapsed_s // recipe.cycle_seconds)
    t = elapsed_s - cycle_index * recipe.cycle_seconds
    cycle = cycle_index + 1

    down_s = recipe.ramp_down_minutes * 60.0
    cold_s = recipe.cold_dwell_minutes * 60.0
    up_s = recipe.ramp_up_minutes * 60.0
    hot_s = recipe.hot_dwell_minutes * 60.0

    # The first ramp down starts from ambient; later ones from the hot dwell.
    ramp_down_from = recipe.start_from_c if cycle_index == 0 else recipe.hot_c

    if t < down_s:
        value = ramp_down_from + (recipe.cold_c - ramp_down_from) * (t / down_s)
        return ProfilePoint(round(value, 1), cycle, Phase.RAMP_DOWN, t, down_s)

    t -= down_s
    if t < cold_s:
        return ProfilePoint(recipe.cold_c, cycle, Phase.COLD_DWELL, t, cold_s)

    t -= cold_s
    if t < up_s:
        value = recipe.cold_c + (recipe.hot_c - recipe.cold_c) * (t / up_s)
        return ProfilePoint(round(value, 1), cycle, Phase.RAMP_UP, t, up_s)

    t -= up_s
    return ProfilePoint(recipe.hot_c, cycle, Phase.HOT_DWELL, t, hot_s)


def is_dwell(phase: Phase) -> bool:
    return phase in (Phase.COLD_DWELL, Phase.HOT_DWELL)


def is_ramp(phase: Phase) -> bool:
    return phase in (Phase.RAMP_DOWN, Phase.RAMP_UP)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def format_hours(seconds: float) -> str:
    hours = seconds / 3600.0
    return f"{hours:.0f} hours" if math.isclose(hours, round(hours), abs_tol=0.05) \
        else f"{hours:.1f} hours"
