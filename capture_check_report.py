"""Render validated capture timing measurements as a self-contained HTML report."""

import heapq
import json
from html import escape

from capture_check import exceeds


MAX_PLOT_POINTS = 600
LONGEST_COUNT = 10


def interval_overview(timestamps):
    """Keep the maximum interval in each elapsed-time bucket, with exact indices."""
    origin = timestamps[0]
    duration = timestamps[-1] - origin
    buckets = {}
    for index, (previous, current) in enumerate(zip(timestamps, timestamps[1:])):
        interval = current - previous
        bucket = min(MAX_PLOT_POINTS - 1, int(((current - origin) / duration) * MAX_PLOT_POINTS))
        if bucket not in buckets or interval > buckets[bucket][1]:
            buckets[bucket] = (index, interval)
    return [buckets[key] for key in sorted(buckets)]


def longest_intervals(timestamps):
    """Return the ten longest intervals, keeping source order for exact ties."""
    intervals = ((index, current - previous) for index, (previous, current)
                 in enumerate(zip(timestamps, timestamps[1:])))
    return heapq.nsmallest(LONGEST_COUNT, intervals, key=lambda item: (-item[1], item[0]))


def _number(value):
    return f"{value:,.6g}"


def _measurement(value, unit):
    return f'<span title="{value!r} {unit}">{_number(value)} {unit}</span>'


def render_html(timestamps, result, *, source_name, field="timestamp", unit="seconds"):
    """Render a report from timestamps already accepted by capture_check.analyze."""
    origin = timestamps[0]
    duration = result["duration_seconds"]
    gap_limit = result["limits"]["maximum_gap_ms"]
    gap_limit_seconds = (1.0 / result["target_fps"]) * result["limits"]["max_gap_frames"]
    target = result["target_interval_ms"]
    largest = result["interval_ms"]["max"]
    scale = max(gap_limit, largest)
    points = interval_overview(timestamps)
    ranked = longest_intervals(timestamps)
    status = "Timing limits passed" if result["status"] == "pass" else "Timing limits failed"
    status_class = "pass" if result["status"] == "pass" else "fail"
    gap_failed = "gap_limit_exceeded" in result["failures"]
    rate_failed = "cadence_below_minimum" in result["failures"]
    location = result["longest_interval"]

    def y(value):
        # Divide before multiplying: large but finite valid inputs stay finite.
        return 240 - (value / scale) * 220

    stems = []
    for index, interval in points:
        interval_ms = interval * 1000
        x = 4 + ((timestamps[index + 1] - origin) / duration) * 992
        point_y = y(interval_ms)
        failed = exceeds(interval, gap_limit_seconds)
        title = (f"Samples {index + 1} to {index + 2}: {interval_ms!r} ms; "
                 f"elapsed {timestamps[index] - origin!r} to {timestamps[index + 1] - origin!r} s")
        stems.append(f'<g class="{"over-limit" if failed else "interval"}"><title>{title}</title>'
                     f'<path d="M{x:.4f} 240V{point_y:.4f}"/>'
                     f'<circle cx="{x:.4f}" cy="{point_y:.4f}" r="2"/></g>')

    rows = []
    for index, interval in ranked:
        interval_ms = interval * 1000
        failed = exceeds(interval, gap_limit_seconds)
        rows.append(
            '<tr>'
            f'<th scope="row">{index + 1:,} → {index + 2:,}</th>'
            f'<td>{_measurement(interval_ms, "ms")}</td>'
            f'<td><span>{timestamps[index] - origin!r}</span> to '
            f'<span>{timestamps[index + 1] - origin!r} s</span></td>'
            f'<td class="{"fail-text" if failed else "pass-text"}">'
            f'{"Above limit" if failed else "Within limit"}</td></tr>'
        )

    plotted = len(points)
    total = result["interval_count"]
    overview_note = (f"All {total:,} intervals shown." if plotted == total else
                     f"Showing {plotted:,} bucket maxima from {total:,} intervals. "
                     f"The elapsed-time range is divided into {MAX_PLOT_POINTS} equal buckets; "
                     "each occupied bucket retains its longest interval. Empty buckets have no plotted event.")
    interpretation = []
    if rate_failed:
        interpretation.append("Observed cadence is below the configured minimum.")
    if gap_failed:
        interpretation.append("At least one interval exceeds the configured gap limit.")
    if not interpretation:
        interpretation.append("Observed cadence and the longest interval are within the configured limits.")
    stats_json = escape(json.dumps(result, indent=2, allow_nan=False))
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{escape(source_name)} | capture-check timing report</title>
<style>
:root {{ color-scheme: light; --ink:#192c3b; --muted:#526474; --line:#cbd5dc; --blue:#155dc3; --red:#a12f1e; --green:#216042; --paper:#fff; --ground:#edf1f4; }}
* {{ box-sizing:border-box; }}
html {{ scroll-behavior:auto; }}
body {{ margin:0; background:var(--ground); color:var(--ink); font:16px/1.55 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
::selection {{ background:#c7dcf9; color:#142b44; }}
a {{ color:var(--blue); text-underline-offset:4px; }}
a:hover {{ text-decoration-thickness:2px; }}
:focus-visible {{ outline:3px solid var(--blue); outline-offset:5px; }}
.sheet {{ max-width:1160px; margin:32px auto; background:var(--paper); padding:32px 48px 40px; }}
header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; padding-bottom:24px; border-bottom:1px solid var(--line); }}
.brand {{ font-weight:750; font-size:21px; letter-spacing:-.025em; }}
header a {{ font-size:14px; }}
h1,h2,p,figure {{ margin:0; }}
h1 {{ font-size:clamp(28px,4vw,42px); line-height:1.12; letter-spacing:-.03em; text-wrap:balance; }}
h2 {{ font-size:22px; line-height:1.25; letter-spacing:-.015em; }}
p {{ max-width:72ch; }}
.finding {{ padding:32px 0 24px; }}
.status-word {{ color:var(--green); }}
.fail .status-word {{ color:var(--red); }}
.source {{ margin:12px 0 8px; overflow-wrap:anywhere; font-weight:650; }}
.muted {{ color:var(--muted); }}
.finding>p:last-child {{ margin-top:6px; }}
.worst {{ margin:0 0 24px; padding:18px 0; border-top:1px solid var(--line); border-bottom:1px solid var(--line); display:flex; flex-wrap:wrap; align-items:baseline; gap:8px 28px; }}
.worst strong {{ font-size:23px; font-weight:700; font-variant-numeric:tabular-nums; }}
.worst p {{ font-size:15px; color:var(--muted); }}
.numerals,td,th,.limits dd {{ font-variant-numeric:tabular-nums; }}
.chart-heading {{ display:flex; justify-content:space-between; gap:16px; align-items:baseline; margin-bottom:16px; }}
.chart-heading p {{ font-size:14px; color:var(--muted); }}
.plot {{ display:grid; grid-template-columns:82px minmax(0,1fr); gap:8px; }}
.y-axis {{ display:flex; flex-direction:column; justify-content:space-between; align-items:flex-end; padding:10px 0 7px; font-size:13px; color:var(--muted); line-height:1; overflow-wrap:anywhere; }}
svg {{ width:100%; height:260px; overflow:visible; }}
svg path,svg line {{ vector-effect:non-scaling-stroke; fill:none; }}
.interval {{ stroke:var(--blue); fill:var(--blue); }}
.interval path {{ opacity:.65; stroke-width:1.3; }}
.over-limit {{ stroke:var(--red); fill:var(--red); }}
.over-limit path {{ stroke-width:2; }}
.grid {{ stroke:var(--line); stroke-width:1; }}
.target {{ stroke:#637484; stroke-dasharray:6 5; stroke-width:1.5; }}
.gap {{ stroke:var(--red); stroke-dasharray:2 4; stroke-width:1.5; }}
.x-axis {{ display:flex; justify-content:space-between; gap:8px; margin-left:90px; font-size:13px; color:var(--muted); }}
.x-axis span:nth-child(2) {{ text-align:center; }}
.legend {{ display:flex; flex-wrap:wrap; gap:8px 24px; margin:20px 0 10px; font-size:14px; }}
.legend span {{ display:inline-flex; align-items:center; gap:8px; }}
.key {{ width:23px; border-top:2px solid var(--blue); flex-shrink:0; }}
.key.target-key {{ border-top:2px dashed #637484; }}
.key.gap-key {{ border-top:2px dotted var(--red); }}
figcaption {{ color:var(--muted); font-size:14px; max-width:82ch; }}
.limits {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:28px; margin:32px 0 0; padding:24px 0; border-top:1px solid var(--line); border-bottom:1px solid var(--line); }}
.limits h2 {{ font-size:17px; margin-bottom:12px; }}
dl {{ margin:0; }}
.limits dl>div {{ display:flex; justify-content:space-between; align-items:baseline; gap:16px; margin-top:6px; }}
dt {{ color:var(--muted); }}
dd {{ margin:0; text-align:right; overflow-wrap:anywhere; }}
.pass-text {{ color:var(--green); }}
.fail-text {{ color:var(--red); }}
.details-section {{ margin-top:36px; }}
.details-section>p {{ margin:8px 0 20px; color:var(--muted); font-size:14px; }}
.table-wrap {{ overflow-x:auto; scrollbar-color:var(--muted) var(--ground); }}
table {{ border-collapse:collapse; width:100%; text-align:left; font-size:14px; }}
th,td {{ padding:12px 16px 12px 0; border-bottom:1px solid #dde4e9; vertical-align:top; }}
thead th {{ font-size:13px; font-weight:650; color:var(--muted); border-bottom:1px solid var(--ink); }}
tbody th {{ font-weight:600; }}
td:last-child,th:last-child {{ padding-right:0; }}
.notes {{ margin-top:32px; padding-top:24px; border-top:1px solid var(--line); }}
.notes h2 {{ font-size:18px; }}
.notes p {{ margin-top:10px; font-size:14px; color:var(--muted); }}
details {{ margin-top:24px; }}
summary {{ cursor:pointer; color:var(--blue); min-height:44px; padding:10px 0; }}
pre {{ padding:16px; background:#edf1f4; font:13px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace; overflow:auto; max-height:480px; scrollbar-color:var(--muted) var(--ground); }}
footer {{ display:flex; justify-content:space-between; gap:20px; margin-top:32px; color:var(--muted); font-size:13px; }}
@media(max-width:700px) {{
 .sheet {{ margin:0; padding:22px 20px 28px; }}
 .limits {{ grid-template-columns:1fr; gap:24px; }}
 .chart-heading {{ display:block; }}
 .chart-heading p {{ margin-top:4px; }}
 .plot {{ grid-template-columns:64px minmax(0,1fr); gap:4px; }}
 .x-axis {{ margin-left:68px; }}
 .worst {{ display:block; }}
 .worst p {{ margin-top:5px; }}
 .finding {{ padding-top:28px; }}
 th,td {{ padding-right:10px; }}
 td span {{ display:inline-block; }}
 footer {{ flex-direction:column; gap:5px; }}
}}
@media(max-width:380px) {{
 .sheet {{ padding-left:14px; padding-right:14px; }}
 table {{ font-size:12px; }}
 thead th {{ font-size:12px; }}
 th,td {{ padding-right:8px; }}
 .x-axis span:nth-child(2) {{ display:none; }}
 header {{ gap:10px; }}
 header a {{ font-size:13px; }}
}}
@media print {{
 body {{ background:white; font-size:11pt; }}
 .sheet {{ margin:0; max-width:none; padding:0; }}
 header a,details {{ display:none; }}
 figure,.limits,tr {{ break-inside:avoid; }}
 .limits {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
}}
</style>
</head>
<body>
<main class="sheet {status_class}">
<header><span class="brand">capture-check</span><a href="#longest">Longest intervals ↓</a></header>
<section class="finding" aria-labelledby="status">
<h1 id="status">Timing limits <span class="status-word">{"passed" if result["status"] == "pass" else "failed"}.</span></h1>
<p class="source">{escape(source_name)}</p>
<p class="muted numerals">{result["timestamp_count"]:,} samples · {total:,} intervals · {_measurement(duration, "s")} elapsed</p>
<p>{" ".join(interpretation)}</p>
</section>
<div class="worst"><strong>Longest interval: {_measurement(largest, "ms")}</strong>
<p>Samples {location["start_sample_index"]:,} → {location["end_sample_index"]:,}<br>
{location["start_elapsed_seconds"]!r} to {location["end_elapsed_seconds"]!r} s since first sample</p></div>
<figure aria-labelledby="chart-title">
<div class="chart-heading"><h2 id="chart-title">Intervals over time</h2><p>Interval duration in milliseconds</p></div>
<div class="plot"><div class="y-axis" aria-hidden="true"><span>{_number(scale)}</span><span>{_number(scale / 2)}</span><span>0</span></div>
<svg viewBox="0 0 1000 260" preserveAspectRatio="none" role="img" aria-labelledby="plot-title plot-description">
<title id="plot-title">{status}: interval timing overview</title>
<desc id="plot-description">{escape(overview_note)} The longest interval is {largest!r} milliseconds at samples {location["start_sample_index"]} to {location["end_sample_index"]}. Exact longest intervals and threshold results follow the chart.</desc>
<path class="grid" d="M0 20H1000M0 130H1000M0 240H1000"/>
<path class="target" d="M0 {y(target):.4f}H1000"/>
<path class="gap" d="M0 {y(gap_limit):.4f}H1000"/>
{"".join(stems)}
</svg></div>
<div class="x-axis numerals"><span>0 s</span><span>Elapsed since first sample</span><span>{_number(duration)} s</span></div>
<div class="legend"><span><i class="key" aria-hidden="true"></i>Interval</span><span><i class="key target-key" aria-hidden="true"></i>Target: {_measurement(target, "ms")}</span><span><i class="key gap-key" aria-hidden="true"></i>Gap limit: {_measurement(gap_limit, "ms")}</span></div>
<figcaption>{escape(overview_note)} Points mark interval-ending events; the chart does not interpolate between them. All statistics use the full log.</figcaption>
</figure>
<section class="limits" aria-label="Configured timing checks">
<div><h2>Capture cadence · <span class="{"fail-text" if rate_failed else "pass-text"}">{"Failed" if rate_failed else "Passed"}</span></h2>
<dl><div><dt>Observed</dt><dd>{_measurement(result["observed_cadence_fps"], "samples/s")}</dd></div>
<div><dt>Target</dt><dd>{_measurement(result["target_fps"], "fps")}</dd></div>
<div><dt>Minimum allowed</dt><dd>{_measurement(result["limits"]["minimum_cadence_fps"], "samples/s")}</dd></div></dl></div>
<div><h2>Interval gaps · <span class="{"fail-text" if gap_failed else "pass-text"}">{"Failed" if gap_failed else "Passed"}</span></h2>
<dl><div><dt>Above gap limit</dt><dd>{result["gaps"]["over_max_gap_limit"]:,} of {total:,}</dd></div>
<div><dt>Above target interval</dt><dd>{result["gaps"]["over_target_interval"]:,} <span class="muted">(informational)</span></dd></div>
<div><dt>Median / p95</dt><dd>{_number(result["interval_ms"]["median"])} / {_number(result["interval_ms"]["p95"])} ms</dd></div></dl></div>
</section>
<section class="details-section" id="longest" aria-labelledby="longest-title">
<h2 id="longest-title">Longest {len(ranked)} of {total:,} intervals</h2>
<p>Exact source intervals, ranked by duration. Equal durations keep their original order.</p>
<div class="table-wrap" tabindex="0" role="region" aria-label="Longest intervals table"><table>
<thead><tr><th scope="col">Samples</th><th scope="col">Duration</th><th scope="col">Elapsed range</th><th scope="col">Gap check</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
</section>
<section class="notes" aria-labelledby="notes-title"><h2 id="notes-title">What this report tells you</h2>
<p>These are timing measurements, not a video quality score. Image content is not analyzed: repeated images, motion smoothness and the number of dropped frames cannot be determined from timestamps alone.</p>
<p>Sample positions are one-based entries in the accepted timestamp sequence, not file line numbers or original frame IDs. Elapsed time uses the input clock and is not a video seek position. Above-target intervals do not by themselves fail the configured checks.</p>
<p>Timestamp field: <strong>{escape(field)}</strong>. Input unit: <strong>{escape(unit)}</strong>. Threshold decisions use full precision with the CLI's floating-point tolerance. Summary values and axes are rounded; elapsed endpoints preserve the analyzed floating-point values.</p>
</section>
<details><summary>Full precision measurements (JSON)</summary><pre>{stats_json}</pre></details>
<footer><span>Generated by capture-check</span><span>Self-contained report · No image content analyzed</span></footer>
</main>
</body>
</html>
'''
