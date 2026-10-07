"""Check the cadence of recorded source-frame timestamps using only Python's stdlib."""

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path


class InputError(ValueError):
    """Input cannot be analyzed reliably."""


class _ObjectPairs(list):
    """Keep JSON object members so repeated timestamp fields are not discarded."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError(message)


def finite_number(value, label):
    if isinstance(value, bool):
        raise InputError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise InputError(f"{label} must be a finite number") from None
    if not math.isfinite(number):
        raise InputError(f"{label} must be a finite number")
    return number


def read_timestamps(path, field="timestamp", unit="seconds"):
    """Read CSV header fields or JSONL object fields, expressed in one clock unit."""
    path = Path(path)
    scale = 0.001 if unit == "milliseconds" else 1.0
    timestamps = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            if path.suffix.lower() == ".csv":
                rows = csv.reader(source, strict=True)
                header = next((row for row in rows if row), None)
                if not header or header.count(field) != 1:
                    raise InputError(f"CSV must have exactly one '{field}' header")
                field_index = header.index(field)
                for row in rows:
                    if not row:
                        continue
                    if len(row) != len(header):
                        raise InputError(f"CSV row ending at line {rows.line_num} has the wrong number of fields")
                    timestamps.append(finite_number(row[field_index], f"line {rows.line_num}: {field}") * scale)
            elif path.suffix.lower() == ".jsonl":
                for line_number, line in enumerate(source, 1):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line, object_pairs_hook=_ObjectPairs)
                    except (ValueError, RecursionError):
                        raise InputError(f"line {line_number} is not valid JSON") from None
                    if not isinstance(row, _ObjectPairs):
                        raise InputError(f"line {line_number} must be an object with '{field}'")
                    values = [value for key, value in row if key == field]
                    if len(values) != 1:
                        raise InputError(f"line {line_number} must have exactly one '{field}'")
                    if not isinstance(values[0], (int, float)):
                        raise InputError(f"line {line_number}: {field} must be a JSON number")
                    timestamps.append(finite_number(values[0], f"line {line_number}: {field}") * scale)
            else:
                raise InputError("input filename must end in .csv or .jsonl")
    except (OSError, UnicodeError, csv.Error) as error:
        raise InputError(f"cannot read input: {getattr(error, 'strerror', None) or str(error)}") from None
    return timestamps


def exceeds(value, limit):
    # Do not classify floating-point rounding at an exact boundary as a stall.
    return value > limit and not math.isclose(value, limit, rel_tol=1e-9, abs_tol=1e-12)


def analyze(timestamps, fps, min_rate_ratio=0.95, max_gap_frames=2.0):
    """Return measurements and threshold results; timestamps are in seconds."""
    fps = finite_number(fps, "fps")
    min_rate_ratio = finite_number(min_rate_ratio, "min-rate-ratio")
    max_gap_frames = finite_number(max_gap_frames, "max-gap-frames")
    if fps <= 0:
        raise InputError("fps must be greater than zero")
    if not 0 < min_rate_ratio <= 1:
        raise InputError("min-rate-ratio must be greater than zero and at most one")
    if max_gap_frames < 1:
        raise InputError("max-gap-frames must be at least one")
    values = [finite_number(value, f"timestamp {index}") for index, value in enumerate(timestamps, 1)]
    if len(values) < 2:
        raise InputError("at least two timestamps are required")
    intervals = []
    for index, (previous, current) in enumerate(zip(values, values[1:]), 2):
        if current <= previous:
            raise InputError(f"timestamp {index} must be greater than timestamp {index - 1}")
        intervals.append(finite_number(current - previous, f"interval ending at timestamp {index}"))
    duration = finite_number(values[-1] - values[0], "duration")
    target_interval = 1.0 / fps
    max_gap = finite_number(target_interval * max_gap_frames, "maximum gap limit")
    observed_rate = finite_number(len(intervals) / duration, "observed cadence")
    sorted_intervals = sorted(intervals)
    # Locate the actual maximum, keeping the first occurrence of an exact tie.
    longest_index = intervals.index(sorted_intervals[-1])
    # Nearest-rank percentile: ceil(0.95 * N), with a one-based rank.
    p95 = sorted_intervals[math.ceil(0.95 * len(intervals)) - 1]
    gap_count = sum(exceeds(interval, max_gap) for interval in intervals)
    rate_failed = exceeds(fps * min_rate_ratio, observed_rate)
    return {
        "status": "fail" if rate_failed or gap_count else "pass",
        "timestamp_count": len(values),
        "interval_count": len(intervals),
        "duration_seconds": duration,
        "observed_cadence_fps": observed_rate,
        "target_fps": fps,
        "target_interval_ms": finite_number(target_interval * 1000, "target interval in milliseconds"),
        "interval_ms": {
            "median": finite_number(statistics.median(intervals) * 1000, "median interval in milliseconds"),
            "p95": finite_number(p95 * 1000, "p95 interval in milliseconds"),
            "max": finite_number(sorted_intervals[-1] * 1000, "maximum interval in milliseconds"),
        },
        "longest_interval": {
            "start_sample_index": longest_index + 1,
            "end_sample_index": longest_index + 2,
            "start_elapsed_seconds": values[longest_index] - values[0],
            "end_elapsed_seconds": values[longest_index + 1] - values[0],
        },
        "gaps": {
            "over_target_interval": sum(exceeds(interval, target_interval) for interval in intervals),
            "over_two_target_intervals": sum(exceeds(interval, target_interval * 2) for interval in intervals),
            "over_max_gap_limit": gap_count,
        },
        "limits": {
            "min_rate_ratio": min_rate_ratio,
            "minimum_cadence_fps": fps * min_rate_ratio,
            "max_gap_frames": max_gap_frames,
            "maximum_gap_ms": finite_number(max_gap * 1000, "maximum gap limit in milliseconds"),
        },
        "failures": (["cadence_below_minimum"] if rate_failed else []) + (["gap_limit_exceeded"] if gap_count else []),
    }


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("input", type=Path, help="CSV with a header, or JSONL with one object per line")
    parser.add_argument("--fps", required=True, type=float, help="target source capture cadence")
    parser.add_argument("--field", default="timestamp", help="timestamp field (default: timestamp)")
    parser.add_argument("--unit", choices=("seconds", "milliseconds"), default="seconds")
    parser.add_argument("--min-rate-ratio", type=float, default=0.95, help="minimum observed/target cadence ratio (default: 0.95)")
    parser.add_argument("--max-gap-frames", type=float, default=2.0, help="maximum gap as a multiple of the target interval (default: 2)")
    parser.add_argument("--html", type=Path, help="write an offline HTML report to a new file (existing paths are refused)")
    try:
        args = parser.parse_args(argv)
        timestamps = read_timestamps(args.input, args.field, args.unit)
        result = analyze(timestamps, args.fps, args.min_rate_ratio, args.max_gap_frames)
        if args.html is not None:
            from capture_check_report import render_html

            created = False
            try:
                document = render_html(timestamps, result, source_name=args.input.name,
                                       field=args.field, unit=args.unit)
                with args.html.open("x", encoding="utf-8") as destination:
                    created = True
                    destination.write(document)
            except (OSError, UnicodeError) as error:
                if created:
                    try:
                        args.html.unlink()
                    except OSError:
                        pass
                raise InputError(f"cannot write HTML report: {error}") from None
        exit_code = 0 if result["status"] == "pass" else 1
    except InputError as error:
        result = {"status": "invalid", "error": str(error)}
        exit_code = 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
