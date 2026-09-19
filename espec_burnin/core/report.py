"""Single-file HTML report.

Self-contained on purpose: no PDF toolchain, opens in any browser, small enough
to email.  The chart is inline SVG drawn from the samples.
"""

from __future__ import annotations

import html
from datetime import datetime

from espec_burnin import __version__
from espec_burnin.core.pace import both_directions, describe
from espec_burnin.core.profile import format_duration

_CSS = """
:root { color-scheme: light dark;
  --bg:#ffffff; --fg:#1a1a1a; --muted:#5b6470; --line:#dfe3e8; --card:#f6f8fa;
  --measured:#2f6feb; --setpoint:#9aa4b2; --bad:#b4232c; }
@media (prefers-color-scheme: dark) { :root {
  --bg:#12151a; --fg:#e8eaed; --muted:#9aa4b2; --line:#2a3039; --card:#1a1f26;
  --measured:#6ea8ff; --setpoint:#6b7482; --bad:#ff7b72; } }
* { box-sizing:border-box; }
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
.wrap { max-width:900px; margin:0 auto; }
h1 { font-size:22px; margin:0 0 4px; }
.verdict { font-size:17px; font-weight:600; margin:16px 0 20px; }
.meta { color:var(--muted); font-size:13px; margin-bottom:24px; }
table { border-collapse:collapse; width:100%; margin:16px 0 24px; font-size:14px; }
th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }
th { font-weight:600; color:var(--muted); font-size:12px; text-transform:uppercase;
  letter-spacing:.04em; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px;
  margin:16px 0 24px; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 14px; }
.stat .k { font-size:12px; color:var(--muted); }
.stat .v { font-size:20px; font-weight:600; margin-top:2px; }
.chart { border:1px solid var(--line); border-radius:8px; padding:12px; background:var(--card); }
svg { width:100%; height:auto; display:block; }
.key { font-size:13px; color:var(--muted); margin-top:8px; }
.swatch { display:inline-block; width:22px; height:3px; vertical-align:middle; margin-right:6px; }
.bad { color:var(--bad); }
.pace { display:grid; grid-template-columns:1fr 1fr; gap:24px; }
@media (max-width:700px) { .pace { grid-template-columns:1fr; } }
.pace p { margin:0 0 10px; }
.pace td.n, .pace th.n { text-align:right; font-variant-numeric:tabular-nums; }
tr.stall td { color:var(--bad); font-weight:600; }
footer { color:var(--muted); font-size:12px; margin-top:32px; border-top:1px solid var(--line);
  padding-top:12px; }
"""


def _chart_svg(recorder, width: int = 860, height: int = 300) -> str:
    samples = [s for s in recorder.samples if s.measured_c is not None]
    if len(samples) < 2:
        return "<p>Not enough data to plot.</p>"

    pad_l, pad_r, pad_t, pad_b = 46, 12, 12, 28
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b

    xs = [s.elapsed_s for s in samples]
    x_min, x_max = min(xs), max(xs) or 1.0
    temps = [s.measured_c for s in samples] + [s.setpoint_c for s in samples]
    y_min, y_max = min(temps) - 5, max(temps) + 5
    y_span = (y_max - y_min) or 1.0

    # Cap drawn points so a 48-hour run does not produce a megabyte of path data.
    step = max(1, len(samples) // 1200)
    drawn = samples[::step]

    def point(sample, value):
        x = pad_l + (sample.elapsed_s - x_min) / (x_max - x_min or 1.0) * plot_w
        y = pad_t + (y_max - value) / y_span * plot_h
        return f"{x:.1f},{y:.1f}"

    measured = " ".join(point(s, s.measured_c) for s in drawn)
    setpoint = " ".join(point(s, s.setpoint_c) for s in drawn)

    ticks = []
    for i in range(5):
        value = y_min + y_span * i / 4
        y = pad_t + (y_max - value) / y_span * plot_h
        ticks.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
            f'stroke="var(--line)" stroke-width="1"/>'
            f'<text x="{pad_l - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" '
            f'fill="var(--muted)">{value:.0f}</text>'
        )

    hours = x_max / 3600
    x_labels = []
    for i in range(5):
        hour = hours * i / 4
        x = pad_l + plot_w * i / 4
        x_labels.append(
            f'<text x="{x:.1f}" y="{height - 8}" text-anchor="middle" font-size="11" '
            f'fill="var(--muted)">{hour:.0f}h</text>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Chamber temperature against elapsed time">'
        + "".join(ticks)
        + f'<polyline points="{setpoint}" fill="none" stroke="var(--setpoint)" '
        f'stroke-width="1.5" stroke-dasharray="4 3"/>'
        + f'<polyline points="{measured}" fill="none" stroke="var(--measured)" '
        f'stroke-width="1.8"/>'
        + "".join(x_labels)
        + "</svg>"
    )


def _pace_table(pace) -> str:
    if not pace.bands:
        return "<p>Not enough movement in this direction to measure.</p>"
    stalled = pace.stalled_bands
    rows = "".join(
        f'<tr class="stall"><td>{b.label}</td><td class="n">{b.minutes:.1f}</td>'
        f'<td class="n">{abs(b.c_per_min):.2f}</td></tr>'
        if b in stalled else
        f'<tr><td>{b.label}</td><td class="n">{b.minutes:.1f}</td>'
        f'<td class="n">{abs(b.c_per_min):.2f}</td></tr>'
        for b in pace.bands
    )
    return (
        '<table><tr><th>Band</th><th class="n">Minutes</th>'
        f'<th class="n">°C/min</th></tr>{rows}</table>'
    )


def _pace_section(recorder) -> str:
    """Where the chamber kept up and where it ran out of capacity.

    A run that ends short of its setpoint looks the same in the summary
    figures whether the chamber is slow throughout or fine until the last few
    degrees. Those are different faults, and only the bands tell them apart.
    """
    cooling, heating = both_directions(
        recorder.samples, recorder.recipe.cold_c, recorder.recipe.hot_c
    )
    return f"""<h2>How the chamber paced itself</h2>
<div class="pace">
  <div><h3>Cooling</h3><p>{html.escape(describe(cooling))}</p>{_pace_table(cooling)}</div>
  <div><h3>Heating</h3><p>{html.escape(describe(heating))}</p>{_pace_table(heating)}</div>
</div>
<p class="key">Time is counted only while the chamber was travelling that way,
 so a dwell is not charged to the band it sat in. The slowest band at the end
 of travel is marked when it is far slower than the rest: that is where the
 chamber ran out of capacity rather than where it was merely slow.</p>"""


def render_report(recorder, *, status: str, elapsed_s: float) -> str:
    r = recorder.recipe
    e = html.escape
    verdict = recorder.verdict(status)
    chamber = (f"{recorder.chamber_model} — Serial {recorder.chamber_serial}"
               if recorder.chamber_model and recorder.chamber_serial
               else "Chamber not recorded")
    failed = "completed within tolerance" not in verdict

    tolerance_pct = (
        100.0 * recorder.dwell_in_tolerance_s / recorder.dwell_total_s
        if recorder.dwell_total_s
        else 0.0
    )

    gaps_rows = "".join(
        f"<tr><td>{g.start.strftime('%d %b %H:%M:%S')}</td>"
        f"<td>{format_duration(g.seconds)}</td></tr>"
        for g in recorder.gaps
        if g.seconds >= 2
    )
    gaps_section = (
        f"<h2>Communication gaps</h2><table><tr><th>Started</th><th>Duration</th></tr>"
        f"{gaps_rows}</table>"
        if gaps_rows
        else "<h2>Communication gaps</h2><p>None longer than two seconds.</p>"
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Burn-in report — {e(recorder.batch)}</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<h1>Burn-in report — {e(recorder.batch)}</h1>
<div class="meta">{e(chamber)} ·
 operator {e(recorder.operator or "not recorded")} ·
 started {recorder.started_at.strftime('%A %d %B %Y, %H:%M')} ·
 port {e(recorder.port)}</div>
<div class="verdict{' bad' if failed else ''}">{e(verdict)}</div>

<div class="grid">
  <div class="stat"><div class="k">Run time</div><div class="v">{format_duration(elapsed_s)}</div></div>
  <div class="stat"><div class="k">Cycles completed</div><div class="v">{recorder.cycles_completed} / {r.cycles}</div></div>
  <div class="stat"><div class="k">Coldest reached</div><div class="v">{recorder.min_c if recorder.min_c is not None else '—'} °C</div></div>
  <div class="stat"><div class="k">Hottest reached</div><div class="v">{recorder.max_c if recorder.max_c is not None else '—'} °C</div></div>
  <div class="stat"><div class="k">Dwell in tolerance</div><div class="v">{tolerance_pct:.1f}%</div></div>
</div>

<div class="chart">{_chart_svg(recorder)}
<div class="key">
  <span class="swatch" style="background:var(--measured)"></span>Measured
  &nbsp;&nbsp;<span class="swatch" style="background:var(--setpoint)"></span>Commanded setpoint
</div></div>

{_pace_section(recorder)}

<h2>Recipe as run</h2>
<table>
<tr><th>Setting</th><th>Value</th></tr>
<tr><td>Preset</td><td>{e(r.name)}</td></tr>
<tr><td>Cycles</td><td>{r.cycles}</td></tr>
<tr><td>Temperature range</td><td>{r.cold_c} °C to {r.hot_c} °C</td></tr>
<tr><td>Cooling ramp</td><td>{r.ramp_down_minutes:.0f} min ({r.cooling_c_per_min:.2f} °C/min)</td></tr>
<tr><td>Heating ramp</td><td>{r.ramp_up_minutes:.0f} min ({r.heating_c_per_min:.2f} °C/min)</td></tr>
<tr><td>Cold dwell</td><td>{r.cold_dwell_minutes:.0f} min</td></tr>
<tr><td>Hot dwell</td><td>{r.hot_dwell_minutes:.0f} min</td></tr>
<tr><td>Tolerance</td><td>±{r.tolerance_c} °C</td></tr>
<tr><td>Guaranteed soak</td><td>{"yes" if r.guaranteed_soak else "no"}</td></tr>
</table>

{gaps_section}

<footer>Espec Burn-In {__version__} · report generated
 {datetime.now().strftime('%d %b %Y %H:%M')} · raw data in run.csv beside this file.<br>
 This program is not a safety system. The chamber's independent over-temperature
 limit controller is the protective device.</footer>
</div></body></html>"""
