#!/usr/bin/env python3
"""Work out where a chamber slows down, from a saved speed test.

Takes either file a measurement leaves behind:

    python tools/analyse_measurement.py "…/Chamber tests/<test>/measurement.csv"
    python tools/analyse_measurement.py "…/chamber-profiles/<test>.json"

The CSV (v0.8.0 and later) carries every sample, so it can show how long was
spent in each band and where progress stopped. The JSON summary (any version)
carries only the banded rates, which still shows the slowdown but not the time.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

BIN_WIDTH_C = 5.0


def from_csv(path: Path) -> int:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if not rows:
        print("The file has no samples in it.")
        return 1

    for direction in ("cooling", "heating"):
        leg = [r for r in rows if r["direction"] == direction]
        if not leg:
            continue

        temps = [float(r["measured_c"]) for r in leg]
        elapsed = [float(r["elapsed_s"]) for r in leg]
        print(f"\n=== {direction.upper()} ===")
        print(f"  samples          : {len(leg)}")
        print(f"  from {temps[0]:+.1f} °C to {temps[-1]:+.1f} °C "
              f"over {(elapsed[-1] - elapsed[0]) / 60:.0f} min")
        print(f"  furthest reached : {min(temps) if direction == 'cooling' else max(temps):+.1f} °C")

        seconds: dict[float, float] = defaultdict(float)
        rates: dict[float, list[float]] = defaultdict(list)
        stalled: dict[float, int] = defaultdict(int)
        for previous, row in zip(leg, leg[1:], strict=False):
            band = float(row["band_c"])
            seconds[band] += float(row["elapsed_s"]) - float(previous["elapsed_s"])
            if row["rate_c_per_min"]:
                rates[band].append(abs(float(row["rate_c_per_min"])))
            if row["counted"] == "0":
                stalled[band] += 1

        print(f"\n  {'band':>10}  {'minutes':>8}  {'°C/min':>8}  note")
        order = sorted(seconds, reverse=direction == "cooling")
        for band in order:
            values = rates.get(band, [])
            rate = sum(values) / len(values) if values else 0.0
            note = ""
            if stalled[band] and not values:
                note = "no progress — stalled here"
            elif stalled[band]:
                note = f"{stalled[band]} samples with no progress"
            print(f"  {band:>+9.1f}  {seconds[band] / 60:>8.1f}  {rate:>8.2f}  {note}")

        slowest = [b for b in order if rates.get(b)]
        if slowest:
            worst = min(slowest, key=lambda b: sum(rates[b]) / len(rates[b]))
            longest = max(seconds, key=lambda b: seconds[b])
            print(f"\n  slowest band     : {worst:+.1f} °C "
                  f"({sum(rates[worst]) / len(rates[worst]):.2f} °C/min)")
            print(f"  most time spent  : {longest:+.1f} °C "
                  f"({seconds[longest] / 60:.0f} min)")
    return 0


def from_json(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    name = data.get("name", "?")
    chamber = " ".join(x for x in (data.get("chamber_model"), data.get("chamber_serial")) if x)
    print(f"{name}{'  ·  ' + chamber if chamber else ''}")
    if data.get("aborted"):
        print("  (the test was stopped early, so this is incomplete)")
    print(f"  coldest reached  : {data.get('reachable_min_c')}")
    print(f"  hottest reached  : {data.get('reachable_max_c')}")

    for direction in ("cooling_rates", "heating_rates"):
        rates = {float(k): v for k, v in (data.get(direction) or {}).items()}
        if not rates:
            continue
        print(f"\n=== {direction.replace('_rates', '').upper()} ===")
        order = sorted(rates, reverse="cooling" in direction)
        for band in order:
            bar = "#" * max(1, int(rates[band] * 10))
            print(f"  {band:>+7.1f} °C  {rates[band]:>6.2f} °C/min  {bar}")
        worst = min(rates, key=lambda b: rates[b])
        print(f"\n  slowest band     : {worst:+.1f} °C ({rates[worst]:.2f} °C/min)")
        print("  Bands with no entry are where the chamber made no measurable "
              "progress.")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"No such file: {path}")
        return 1
    return from_csv(path) if path.suffix.lower() == ".csv" else from_json(path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
