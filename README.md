# capture-check

A small command-line tool for checking the timing of captured source frames.
Give it a CSV or JSONL file containing timestamps from your capture process. It
reports interval median, p95, maximum, observed cadence and gaps against a target
frame rate, and locates the longest interval in your timestamp log. It exits with
a failure status if your chosen limits are exceeded.

This is a timestamp checker, not a video-quality score. It has no runtime
dependencies beyond Python 3.10 or newer.

## Quick start

Clone the repository and run directly, without installing a package:

```sh
git clone https://github.com/MohammediYunus/capture-check.git
cd capture-check
python3 -m capture_check examples/steady-60.csv --fps 60
```

Or install into your own virtual environment and use the command:

```sh
python3 -m pip install .
capture-check examples/steady-60.csv --fps 60
```

The package is not published to a registry. Local installation uses setuptools
as a build dependency; direct execution and the tests only use Python's standard
library.

## Try a stall

The checked-in CSV and JSONL fixtures are synthetic. The steady sample spaces
every timestamp 1/60 second apart; the stall sample adds a 200 ms delay before
the fifth interval completes.

```sh
python3 -m capture_check examples/steady-60.csv --fps 60
python3 -m capture_check examples/stall-60.jsonl --fps 60
```

Selected output fields, rounded here for readability:

| Report field | Steady sample | Stall sample |
| --- | --- | --- |
| status | pass | fail |
| observed_cadence_fps | 60.00 | 27.27 |
| interval_ms.median | 16.67 | 16.67 |
| interval_ms.p95 | 16.67 | 216.67 |
| interval_ms.max | 16.67 | 216.67 |
| gaps.over_max_gap_limit | 0 | 1 |
| Exit code | 0 | 1 |

The stall sample fails both default limits. Its median interval stays unchanged,
which is why checking only the median can hide a recording stall. The full JSON
also includes the chosen limits and failure reasons.

## Input

CSV requires a header and one timestamp per row:

```csv
timestamp
0.000000000
0.016666667
0.033333333
```

JSONL requires one object per nonblank line, with exactly one numeric timestamp
field at the top level:

```json
{"timestamp": 0.0}
{"timestamp": 0.016666667}
{"timestamp": 0.033333333}
```

Use one monotonic clock throughout. Values must be finite and strictly
increasing. Duplicate timestamps are invalid. At least two timestamps are
required; use a longer sample for a useful assessment. Extra named fields are
ignored. Blank lines are ignored. JSON strings such as `"0.1"` are not numeric
timestamps. Repeated timestamp fields are invalid, even if their values match.
The filename extension must be .csv or .jsonl.

The default field is `timestamp` and the default unit is seconds. To use another
field or milliseconds:

```sh
python3 -m capture_check recording.csv --fps 60 --field clock_ms --unit milliseconds
```

Use relative timestamps if your recording system can provide them. Large
absolute clock values can lose sub-frame precision when represented as floating
point numbers. Clock resets and merged recordings must be separated before
analysis. This tool never sorts timestamps to hide invalid ordering.

## Where do timestamps come from?

**Only have an MP4?** This tool cannot recover the original source-frame arrival
times from it. File frame timestamps describe the stored playback timeline; a
constant-frame-rate encoder may repeat frames or assign regular timestamps.
Converting that timeline to CSV does not recover capture events that were never
logged. [FFprobe](https://ffmpeg.org/ffprobe.html) can inspect the stored timeline,
but its output is not a substitute for a source capture log.

**Already building a capture pipeline?** Log one timestamp at a precisely defined
event, such as when a captured source frame is accepted by your recording queue:

1. Read the same monotonic clock for every event.
2. Buffer the timestamps in memory while recording. Avoid adding a synchronous
   disk write to every frame, which can disturb the timing you are measuring.
3. After recording stops, subtract the first timestamp and write a CSV with a
   `timestamp` header, or JSONL objects with a numeric `timestamp` field.
4. Run capture-check with the cadence your pipeline was intended to capture.

Record what event the clock represents alongside your data. Render callbacks,
source arrivals, queue acceptance and encoder output are different events. A
regular update callback is not evidence that a new source image was captured.
This project does not currently ship a Unity or OBS exporter.

For a real producer example, the optional
[macOS ScreenCaptureKit calibration window](examples/macos-screencapturekit/README.md)
exports presentation timestamps from its own animated window. It needs macOS 15+,
Xcode 16+ and existing Screen Recording access; it never requests permission.
It saves no images or audio. The example measures its own ScreenCaptureKit
stream, and a pause in animation does not guarantee a gap in its timestamps.

### Portty frame manifests

[Portty's frame recorder](https://github.com/chestso/portty/blob/570cdd6d2ba2abe456b80d7d995e7e6221a5ab36/src/portty_frame_rec.c#L91)
writes **frames.csv** with **index,timestamp,filename** columns. It works directly
with capture-check; the extra columns are ignored. After recording stops, use the
frame rate configured for that recording, for example:

```sh
capture-check frames.csv --fps 30
```

Timestamps are seconds since recording started, rounded to milliseconds. At
30 fps, 33/34 ms intervals can produce a nonzero **over_target_interval** count
without failing the default limits. That count alone does not prove frame loss.

The clock is sampled before the image read/write attempt. The
[backend advances the manifest even when saving fails](https://github.com/chestso/portty/blob/570cdd6d2ba2abe456b80d7d995e7e6221a5ab36/src/backend_sdl3.c#L2192),
so this checks logged cadence, not whether image files were saved or their
contents changed. Longest-interval indices are timestamp sample positions, not
Portty's **index** values; elapsed endpoints are relative to the first sample.

Try the [real Portty recording example](examples/portty/README.md): an unchanged
314-row manifest, the exact recording script and provenance. It was checked with
capture-check 0.2.0 and a separate local image audit. You can analyze the supplied
CSV without installing Portty, or use a working Portty build to record your own.

### Unity and OBS

- [Unity Recorder](https://docs.unity3d.com/Packages/com.unity.recorder@5.1/manual/RecorderWindowRecordingProperties.html)
  distinguishes Constant timing, which equalizes recorded intervals, from Variable
  timing. Know the recording mode before interpreting any exported timestamps.
- [Unity Frame Timing](https://docs.unity3d.com/Manual/frame-timing-manager-get-timing-data.html)
  reports rendering events. Those measurements need an explicit mapping to the
  frames your recorder accepted before they can describe capture cadence.
- [OBS GetStats](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md#getstats)
  exposes aggregate counts, not the per-frame timestamp sequence this CLI needs.
  The [OBS asynchronous source API](https://docs.obsproject.com/reference-sources)
  carries source-frame timestamps, but exporting those requires a source-specific
  integration. A normal OBS recording is not automatically a compatible log.

The **steady-60.csv** and **stall-60.jsonl** files are synthetic timing fixtures,
not recordings from Unity or OBS. They let you learn the output and thresholds
before instrumenting an actual capture process.

## Results and thresholds

Results are JSON on stdout. Exit codes are:

| Code | Meaning |
| --- | --- |
| 0 | Valid input; the configured limits pass |
| 1 | Valid input; at least one limit fails |
| 2 | Invalid input, unreadable file or invalid arguments |

The default limits require observed cadence to be at least 95% of the target and
every interval to be at most two target frame periods. Both must pass. These are
adjustable starting points, not universal quality standards:

```sh
python3 -m capture_check recording.jsonl --fps 60 --min-rate-ratio 0.98 --max-gap-frames 1.5
```

Cadence is the number of intervals divided by the elapsed time between the first
and last timestamps. Median uses the middle interval, averaging the two central
values for an even count. P95 uses the nearest-rank method: rank
ceil(0.95 × interval count). Gap counts are strictly above their named limits;
small floating-point rounding differences at a boundary are ignored. Output
contains the actual limits used. A short stall can fail the maximum-gap limit
even when the average cadence passes.

### Locate the longest interval

Every valid report includes **longest_interval**, which locates the interval whose
duration is reported in **interval_ms.max**. For example, these timestamps:

```csv
timestamp
1000
1000.03125
1000.3125
1000.34375
```

produce this part of the report:

```json
{
  "longest_interval": {
    "start_sample_index": 2,
    "end_sample_index": 3,
    "start_elapsed_seconds": 0.03125,
    "end_elapsed_seconds": 0.3125
  }
}
```

Sample indices are **one-based positions in the timestamp sequence**. They do
not count the CSV header, blank lines or lines within quoted metadata. They are
not physical file line numbers or original captured-frame numbers: a producer
may have omitted frames before exporting its timestamps.

Elapsed endpoints are in seconds relative to the first supplied timestamp,
including when the input uses milliseconds. They describe the logged event's
clock, not necessarily positions you can seek to in a video. If multiple
intervals have exactly the same maximum duration, the first one is reported.
The threshold rounding tolerance does not affect which interval is the maximum.
This field is present for passing reports as well as threshold failures; invalid
input still produces only an invalid status and error message.

## What this does not prove

- A video encoded at 60 fps does not prove there were 60 distinct source frames
  per second. Encoders can repeat frames.
- Timestamps alone cannot detect identical image content. If a capture process
  records a new timestamp for the same picture, this tool cannot detect that.
- Results are only as meaningful as the clock and event you log. Capture source
  frame arrivals, rather than encoder output ticks, if source timing is what you
  want to assess.
- It does not inspect images, audio, resolution, compression or browser playback.
  A passing timing check does not guarantee perceived smoothness.
- Gap counts identify timing intervals, not an exact number of dropped frames.

## Development

```sh
python3 -m unittest discover -s tests -v
```

The unit tests use synthetic timestamps. They cover steady 30/60 cadence, stalls,
threshold boundaries, percentile calculation, malformed files and invalid clocks.
CI runs this small test suite and checks the installed command against synthetic
fixtures and the recorded Portty manifest from outside the checkout, on standard
public GitHub-hosted runners. No paid services or tokens
are needed.

Bug reports with a minimal synthetic timestamp sample, expected result and Python
version are welcome. Please avoid including private recording metadata. For
changes, add a regression test and run the suite above.

MIT licensed. See LICENSE.
