# capture-check

A small command-line tool for checking the timing of captured source frames.
Give it a CSV or JSONL file containing timestamps from your capture process. It
reports interval median, p95, maximum, observed cadence and gaps against a target
frame rate. It exits with a failure status if your chosen limits are exceeded.

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

The examples are synthetic. The steady sample spaces every timestamp 1/60 second
apart; the stall sample adds a 200 ms delay before the fifth interval completes.

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

JSONL requires one object per nonblank line, with a numeric timestamp field:

```json
{"timestamp": 0.0}
{"timestamp": 0.016666667}
{"timestamp": 0.033333333}
```

Use one monotonic clock throughout. Values must be finite and strictly
increasing. Duplicate timestamps are invalid. At least two timestamps are
required; use a longer sample for a useful assessment. Extra named fields are
ignored. Blank lines are ignored. JSON strings such as `"0.1"` are not numeric
timestamps. The filename extension must be .csv or .jsonl.

The default field is `timestamp` and the default unit is seconds. To use another
field or milliseconds:

```sh
python3 -m capture_check recording.csv --fps 60 --field clock_ms --unit milliseconds
```

Use relative timestamps if your recording system can provide them. Large
absolute clock values can lose sub-frame precision when represented as floating
point numbers. Clock resets and merged recordings must be separated before
analysis. This tool never sorts timestamps to hide invalid ordering.

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

The tests use synthetic timestamps only. They cover steady 30/60 cadence, stalls,
threshold boundaries, percentile calculation, malformed files and invalid clocks.
CI runs this small test suite and checks the installed command from outside the
checkout on standard public GitHub-hosted runners. No paid services or tokens
are needed.

Bug reports with a minimal synthetic timestamp sample, expected result and Python
version are welcome. Please avoid including private recording metadata. For
changes, add a regression test and run the suite above.

MIT licensed. See LICENSE.
