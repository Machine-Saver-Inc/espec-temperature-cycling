"""Measuring what the chamber can actually do.

A commanded ramp the chamber cannot follow becomes a step change, and the
recorded profile stops meaning anything.  How fast an Espec can actually move
depends on the load and on how much heat leaks through the cable entry ports,
so it has to be measured rather than assumed.

Two things make a single "max degC/min" figure misleading, and this module
avoids both:

* Rate is not constant. A chamber that pulls down at 3 degC/min around ambient
  may manage 0.4 degC/min over the last ten degrees to -20. So the rate is
  recorded per temperature band and integrated, rather than averaged.
* The empty chamber is the best case, not the operating case. A profile records
  how the chamber was loaded, and recipes are checked against the profile that
  matches the way the run will actually be set up.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)

BIN_WIDTH_C = 5.0
DEFAULT_PLATEAU_C_PER_MIN = 0.05   # below this, the chamber has stopped moving
DEFAULT_PLATEAU_MINUTES = 10.0
DEFAULT_SLOPE_WINDOW_S = 90.0
DEFAULT_SAMPLE_INTERVAL_S = 5.0
DEFAULT_TIMEOUT_MINUTES = 240.0


def bin_for(temperature_c: float) -> float:
    """The centre of the temperature band a reading belongs to."""
    return math.floor(temperature_c / BIN_WIDTH_C) * BIN_WIDTH_C + BIN_WIDTH_C / 2


class Direction(str, Enum):
    COOLING = "cooling"
    HEATING = "heating"


@dataclass
class ChamberProfile:
    """What one chamber, set up one way, can actually do.

    The chamber's model and serial are the identity; ``name`` is the name of
    this particular test against it, so one chamber can hold several.
    """

    chamber_model: str = ""
    chamber_serial: str = ""
    name: str = "Test"
    loaded: bool = True
    load_notes: str = ""
    measured_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    app_version: str = ""

    # band centre (degC) -> degC per minute, as a positive magnitude
    cooling_rates: dict[str, float] = field(default_factory=dict)
    heating_rates: dict[str, float] = field(default_factory=dict)

    reachable_min_c: float | None = None
    reachable_max_c: float | None = None
    ambient_c: float | None = None
    aborted: bool = False

    # -- queries -------------------------------------------------------------
    def _rates(self, direction: Direction) -> dict[float, float]:
        raw = self.cooling_rates if direction is Direction.COOLING else self.heating_rates
        return {float(k): v for k, v in raw.items() if v > 0}

    def rate_at(self, temperature_c: float, direction: Direction) -> float | None:
        """degC/min the chamber manages near this temperature, or None."""
        rates = self._rates(direction)
        if not rates:
            return None
        band = bin_for(temperature_c)
        if band in rates:
            return rates[band]
        # Fall back to the nearest measured band rather than pretending.
        nearest = min(rates, key=lambda b: abs(b - band))
        return rates[nearest]

    def minutes_to_traverse(self, from_c: float, to_c: float) -> float | None:
        """Integrate the measured rate curve across a span.

        This is the number a single average hides: most of the time is spent in
        the last few degrees.
        """
        if math.isclose(from_c, to_c):
            return 0.0
        direction = Direction.COOLING if to_c < from_c else Direction.HEATING
        if not self._rates(direction):
            return None

        low, high = sorted((from_c, to_c))
        total = 0.0
        edge = math.floor(low / BIN_WIDTH_C) * BIN_WIDTH_C
        while edge < high:
            segment_low = max(edge, low)
            segment_high = min(edge + BIN_WIDTH_C, high)
            span = segment_high - segment_low
            if span > 0:
                rate = self.rate_at((segment_low + segment_high) / 2, direction)
                if not rate:
                    return None
                total += span / rate
            edge += BIN_WIDTH_C
        return total

    def recommended_minutes(self, from_c: float, to_c: float, margin: float = 1.15) -> int | None:
        """Traversal time with headroom, rounded up to whole minutes."""
        measured = self.minutes_to_traverse(from_c, to_c)
        if measured is None:
            return None
        return int(math.ceil(measured * margin))

    def can_reach(self, temperature_c: float) -> bool:
        if self.reachable_min_c is not None and temperature_c < self.reachable_min_c - 0.5:
            return False
        if self.reachable_max_c is not None and temperature_c > self.reachable_max_c + 0.5:
            return False
        return True

    # -- identity -------------------------------------------------------------
    @property
    def chamber_label(self) -> str:
        from espec_burnin.core.chambers import Chamber

        return Chamber(model=self.chamber_model, serial=self.chamber_serial).label

    @property
    def chamber_key(self) -> str:
        from espec_burnin.core.chambers import Chamber

        return Chamber(model=self.chamber_model, serial=self.chamber_serial).key

    # -- persistence ---------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ChamberProfile:
        fields = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (data or {}).items() if k in fields})


def profiles_dir() -> Path:
    return Path.home() / ".espec-burn-in" / "chamber-profiles"


def save_profile(profile: ChamberProfile) -> Path:
    """Store a test under its chamber, so one chamber can hold several."""
    from espec_burnin.core.chambers import slug

    folder = profiles_dir() / profile.chamber_key
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug(profile.name)}.json"
    path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    return path


def load_profiles() -> list[ChamberProfile]:
    """Every saved test, newest first.

    rglob also reads the flat layout written before profiles belonged to a
    chamber, so measurements taken with an earlier version are not lost.
    """
    folder = profiles_dir()
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.rglob("*.json")):
        try:
            out.append(ChamberProfile.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda p: p.measured_at, reverse=True)


def load_profiles_for(model: str, serial: str) -> list[ChamberProfile]:
    """The tests run against one chamber, newest first."""
    from espec_burnin.core.chambers import Chamber

    wanted = Chamber(model=model, serial=serial).key
    return [p for p in load_profiles() if p.chamber_key == wanted]


def best_profile_for(model: str, serial: str) -> ChamberProfile | None:
    """The test to check a recipe against: a loaded one over an empty one."""
    profiles = [p for p in load_profiles_for(model, serial) if not p.aborted]
    loaded = [p for p in profiles if p.loaded]
    return (loaded or profiles or [None])[0]


@dataclass
class CapabilityProgress:
    direction: Direction | None
    measured_c: float | None
    target_c: float
    elapsed_s: float
    rate_c_per_min: float | None
    message: str
    done: bool = False


@dataclass
class CapabilitySettings:
    """Where to drive the chamber, and the limits that apply while doing it.

    The clamp is the same one a run uses. Measuring the chamber is still
    driving the chamber, so it cannot be a way around the safety limits.
    """

    cold_target_c: float = -25.0
    hot_target_c: float = 85.0
    absolute_min_c: float = -25.0
    absolute_max_c: float = 85.0
    sample_interval_s: float = DEFAULT_SAMPLE_INTERVAL_S
    slope_window_s: float = DEFAULT_SLOPE_WINDOW_S
    plateau_c_per_min: float = DEFAULT_PLATEAU_C_PER_MIN
    plateau_minutes: float = DEFAULT_PLATEAU_MINUTES
    timeout_minutes: float = DEFAULT_TIMEOUT_MINUTES
    idle_c: float = 25.0

    def clamped(self, celsius: float) -> float:
        return max(self.absolute_min_c, min(self.absolute_max_c, celsius))

    @property
    def cold_target_clamped(self) -> float:
        return self.clamped(self.cold_target_c)

    @property
    def hot_target_clamped(self) -> float:
        return self.clamped(self.hot_target_c)

    @property
    def targets_were_limited(self) -> bool:
        return (self.cold_target_clamped != self.cold_target_c
                or self.hot_target_clamped != self.hot_target_c)


class CapabilityTest:
    """Drives the chamber to each extreme and records how fast it got there.

    Free of Qt so it can be run headlessly and at a time-scale far above real
    time, the same as RunController.
    """

    def __init__(
        self,
        driver,
        profile_name: str,
        settings: CapabilitySettings | None = None,
        *,
        chamber_model: str = "",
        chamber_serial: str = "",
        loaded: bool = True,
        load_notes: str = "",
        on_progress: Callable[[CapabilityProgress], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.driver = driver
        self.settings = settings or CapabilitySettings()
        self.profile = ChamberProfile(
            chamber_model=chamber_model,
            chamber_serial=chamber_serial,
            name=profile_name,
            loaded=loaded,
            load_notes=load_notes,
        )
        self.on_progress = on_progress or (lambda progress: None)
        self.clock = clock
        self.sleep = sleep
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> ChamberProfile:
        started = self.clock()
        try:
            ambient = self.driver.read_temperature()
        except Exception as exc:  # noqa: BLE001 - surfaced as an aborted profile
            log.warning("capability test could not start: %s", exc)
            self.profile.aborted = True
            return self.profile
        self.profile.ambient_c = ambient

        # Clamp here, not at the call site: this is the only place that
        # commands a setpoint during a measurement.
        self._leg(Direction.COOLING, self.settings.cold_target_clamped, started)
        if not self._stop.is_set():
            self._leg(Direction.HEATING, self.settings.hot_target_clamped, started)

        try:
            self.driver.write_setpoint(self.settings.clamped(self.settings.idle_c))
        except Exception as exc:  # noqa: BLE001 - nothing more to do
            log.warning("could not return the chamber to idle: %s", exc)

        self.profile.aborted = self._stop.is_set()
        self._emit(None, self.settings.idle_c, started, None,
                   "Finished. The chamber is returning to room temperature.", done=True)

        return self.profile

    # -- one direction -------------------------------------------------------
    def _leg(self, direction: Direction, target_c: float, started: float) -> None:
        target_c = self.settings.clamped(target_c)
        try:
            self.driver.write_setpoint(target_c)
        except Exception as exc:  # noqa: BLE001 - treated as an abort
            log.warning("could not command %s: %s", target_c, exc)
            self._stop.set()
            return

        samples: list[tuple[float, float]] = []      # (clock, temperature)
        per_bin: dict[float, list[float]] = {}
        plateau_since: float | None = None
        extreme: float | None = None
        leg_start = self.clock()

        while not self._stop.is_set():
            now = self.clock()
            if (now - leg_start) / 60.0 > self.settings.timeout_minutes:
                break

            try:
                temperature = self.driver.read_temperature()
            except Exception as exc:  # noqa: BLE001 - a gap, not a failure
                log.debug("capability read failed: %s", exc)
                self.sleep(self.settings.sample_interval_s)
                continue

            samples.append((now, temperature))
            extreme = (
                temperature if extreme is None else
                (min(extreme, temperature) if direction is Direction.COOLING
                 else max(extreme, temperature))
            )

            rate = self._slope_c_per_min(samples)
            if rate is not None:
                magnitude = abs(rate)
                moving_the_right_way = (
                    rate < 0 if direction is Direction.COOLING else rate > 0
                )
                if moving_the_right_way and magnitude > self.settings.plateau_c_per_min:
                    per_bin.setdefault(bin_for(temperature), []).append(magnitude)
                    plateau_since = None
                else:
                    if plateau_since is None:
                        plateau_since = now
                    elif (now - plateau_since) / 60.0 >= self.settings.plateau_minutes:
                        break   # the chamber has stopped making progress

            reached = (
                temperature <= target_c if direction is Direction.COOLING
                else temperature >= target_c
            )
            self._emit(direction, target_c, started, rate,
                       f"{'Cooling' if direction is Direction.COOLING else 'Heating'} "
                       f"— {temperature:.1f} °C, heading for {target_c:.0f} °C",
                       measured=temperature)
            if reached:
                break
            self.sleep(self.settings.sample_interval_s)

        # Median per band: robust to the odd noisy sample, unlike the maximum.
        rates = {str(band): round(statistics.median(values), 3)
                 for band, values in per_bin.items() if values}
        if direction is Direction.COOLING:
            self.profile.cooling_rates = rates
            self.profile.reachable_min_c = extreme
        else:
            self.profile.heating_rates = rates
            self.profile.reachable_max_c = extreme

    def _slope_c_per_min(self, samples: list[tuple[float, float]]) -> float | None:
        """Least-squares slope over the recent window, in degC per minute."""
        if len(samples) < 3:
            return None
        cutoff = samples[-1][0] - self.settings.slope_window_s
        window = [s for s in samples if s[0] >= cutoff]
        if len(window) < 3:
            return None
        times = [s[0] for s in window]
        temps = [s[1] for s in window]
        mean_t = sum(times) / len(times)
        mean_y = sum(temps) / len(temps)
        denominator = sum((t - mean_t) ** 2 for t in times)
        if denominator <= 0:
            return None
        slope_per_second = sum(
            (t - mean_t) * (y - mean_y) for t, y in zip(times, temps, strict=True)
        ) / denominator
        return slope_per_second * 60.0

    def _emit(self, direction, target_c, started, rate, message,
              measured: float | None = None, done: bool = False) -> None:
        self.on_progress(
            CapabilityProgress(
                direction=direction,
                measured_c=measured,
                target_c=target_c,
                elapsed_s=self.clock() - started,
                rate_c_per_min=rate,
                message=message,
                done=done,
            )
        )
