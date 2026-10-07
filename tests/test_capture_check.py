import contextlib
import io
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from capture_check import InputError, analyze, main, read_timestamps


class CadenceTests(unittest.TestCase):
    def test_steady_60(self):
        result = analyze([i / 60 for i in range(121)], 60)
        self.assertEqual(result["status"], "pass")
        self.assertAlmostEqual(result["observed_cadence_fps"], 60)
        self.assertAlmostEqual(result["interval_ms"]["median"], 1000 / 60)
        self.assertAlmostEqual(result["interval_ms"]["p95"], 1000 / 60)
        self.assertAlmostEqual(result["interval_ms"]["max"], 1000 / 60)
        self.assertEqual(result["gaps"]["over_target_interval"], 0)

    def test_steady_30_passes_at_30_but_not_60(self):
        times = [i / 30 for i in range(61)]
        self.assertEqual(analyze(times, 30)["status"], "pass")
        result = analyze(times, 60)
        self.assertEqual(result["failures"], ["cadence_below_minimum"])
        self.assertEqual(result["gaps"]["over_target_interval"], 60)
        self.assertEqual(result["gaps"]["over_two_target_intervals"], 0)

    def test_short_stall_fails_even_when_average_is_acceptable(self):
        times = [i / 60 + (0.2 if i >= 60 else 0) for i in range(601)]
        result = analyze(times, 60)
        self.assertEqual(result["failures"], ["gap_limit_exceeded"])
        self.assertEqual(result["gaps"]["over_max_gap_limit"], 1)
        self.assertAlmostEqual(result["interval_ms"]["max"], 216.6666666667)

    def test_nearest_rank_percentile(self):
        times = [0.0]
        for gap in range(1, 21):
            times.append(times[-1] + gap / 1000)
        result = analyze(times, 60)
        self.assertAlmostEqual(result["interval_ms"]["median"], 10.5)
        self.assertAlmostEqual(result["interval_ms"]["p95"], 19)
        self.assertAlmostEqual(result["interval_ms"]["max"], 20)

    def test_custom_limits_and_exact_boundaries(self):
        times = [i / 60 for i in range(61)]
        self.assertEqual(analyze(times, 60, min_rate_ratio=1, max_gap_frames=1)["status"], "pass")
        result = analyze([0, 0.02, 0.04], 60, min_rate_ratio=0.8, max_gap_frames=1.1)
        self.assertEqual(result["failures"], ["gap_limit_exceeded"])

    def test_non_monotonic_duplicate_and_short_inputs(self):
        for times in ([0, 0.02, 0.01], [0, 0, 0.02], [], [1]):
            with self.subTest(times=times), self.assertRaises(InputError):
                analyze(times, 60)

    def test_non_finite_and_overflow(self):
        for times in ([0, math.nan], [0, math.inf], [0, True], [-1e308, 1e308], [0, 1e308]):
            with self.subTest(times=times), self.assertRaises(InputError):
                analyze(times, 60)

    def test_invalid_limits(self):
        for kwargs in ({"fps": 0}, {"fps": -1}, {"fps": math.nan}, {"fps": 60, "min_rate_ratio": 1.01}, {"fps": 60, "min_rate_ratio": 0}, {"fps": 60, "max_gap_frames": 0.5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(InputError):
                analyze([0, 1 / 60], **kwargs)


class InputAndCliTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def fixture(self, content, suffix=".jsonl"):
        path = Path(self.folder.name) / ("timestamps" + suffix)
        path.write_text(content, encoding="utf-8")
        return path

    def run_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(args))
        return code, json.loads(output.getvalue())

    def test_csv_custom_field_and_milliseconds(self):
        path = self.fixture("clock,label\n0,start\n16.666666666667,next\n33.333333333333,last\n", ".csv")
        code, result = self.run_cli(str(path), "--fps", "60", "--field", "clock", "--unit", "milliseconds")
        self.assertEqual(code, 0)
        self.assertAlmostEqual(result["observed_cadence_fps"], 60)

    def test_csv_leading_blank_lines_and_quoted_metadata(self):
        path = self.fixture('\n\r\ntimestamp,note\r\n0,"line one\n\nline two"\r\n\r\n0.02,last\r\n', ".csv")
        code, result = self.run_cli(str(path), "--fps", "50")
        self.assertEqual((code, result["status"]), (0, "pass"))
        self.assertEqual(result["timestamp_count"], 2)

    def test_csv_errors_keep_physical_line_numbers_after_blanks(self):
        for content, line in (
            ('\n\ntimestamp,note\n0,"first\nsecond"\n\ninvalid,last\n', 7),
            ('\n\ntimestamp,note\n0,"first\nsecond"\n\n0.02\n', 7),
        ):
            with self.subTest(content=content):
                code, result = self.run_cli(str(self.fixture(content, ".csv")), "--fps", "50")
                self.assertEqual((code, result["status"]), (2, "invalid"))
                self.assertIn(f"line {line}", result["error"])

    def test_jsonl_pass_output(self):
        path = self.fixture('\n{"timestamp": 0, "unused": true}\n{"timestamp": 0.02}\n\n')
        code, result = self.run_cli(str(path), "--fps", "50")
        self.assertEqual((code, result["status"]), (0, "pass"))

    def test_jsonl_repeated_selected_timestamp_is_invalid(self):
        for field, line in (
            ("timestamp", '{"timestamp": 1, "timestamp": 0}'),
            ("timestamp", '{"timestamp": 0, "timestamp": 0}'),
            ("timestamp", '{"timestamp": 0, "time\\u0073tamp": 0}'),
            ("clock_ms", '{"clock_ms": 1, "clock_ms": 0}'),
        ):
            with self.subTest(field=field, line=line):
                path = self.fixture(line + '\n' + json.dumps({field: 0.02}) + '\n')
                code, result = self.run_cli(str(path), "--fps", "50", "--field", field)
                self.assertEqual((code, result["status"]), (2, "invalid"))
                self.assertIn(f"line 1 must have exactly one '{field}'", result["error"])

    def test_jsonl_ignored_metadata_does_not_supply_a_timestamp(self):
        path = self.fixture(
            '{"timestamp": 0, "metadata": {"timestamp": 4, "timestamp": 5}, "note": 1, "note": 2}\n'
            '{"timestamp": 0.02, "metadata": [{"timestamp": 9}]}\n'
        )
        code, result = self.run_cli(str(path), "--fps", "50")
        self.assertEqual((code, result["status"]), (0, "pass"))
        code, result = self.run_cli(str(self.fixture('{"metadata": {"timestamp": 0}}\n')), "--fps", "50")
        self.assertEqual((code, result["status"]), (2, "invalid"))

    def test_threshold_failure_exit_code(self):
        path = self.fixture('{"timestamp": 0}\n{"timestamp": 0.2}\n')
        code, result = self.run_cli(str(path), "--fps", "60")
        self.assertEqual((code, result["status"]), (1, "fail"))

    def test_invalid_jsonl(self):
        for content in ('oops\n', '{}\n', '[]\n', '{"timestamp": "0"}\n', '{"timestamp": null}\n', '{"timestamp": true}\n', '{"timestamp": NaN}\n', '[' * 2000 + '0' + ']' * 2000):
            with self.subTest(content=content):
                code, result = self.run_cli(str(self.fixture(content)), "--fps", "60")
                self.assertEqual((code, result["status"]), (2, "invalid"))

    def test_invalid_csv(self):
        for content in ("wrong\n0\n", "timestamp,timestamp\n0,1\n", "timestamp,label\n0\n", "timestamp\n0,1\n", "timestamp\nnope\n", 'timestamp\n"unterminated\n'):
            with self.subTest(content=content):
                code, result = self.run_cli(str(self.fixture(content, ".csv")), "--fps", "60")
                self.assertEqual((code, result["status"]), (2, "invalid"))

    def test_missing_file_and_bad_options_are_json(self):
        for args in (("missing.jsonl", "--fps", "60"), ("missing.jsonl",), ("missing.jsonl", "--fps", "oops"), ("missing.jsonl", "--fps", "60", "--unknown")):
            with self.subTest(args=args):
                code, result = self.run_cli(*args)
                self.assertEqual((code, result["status"]), (2, "invalid"))

    def test_unsupported_extension(self):
        with self.assertRaises(InputError):
            read_timestamps(self.fixture("0\n1\n", ".txt"))

    def test_process_exit_codes(self):
        for content, expected in (("timestamp\n0\n0.02\n", 0), ("timestamp\n0\n0.2\n", 1), ("timestamp\n0\n0\n", 2)):
            path = self.fixture(content, ".csv")
            process = subprocess.run([sys.executable, "-m", "capture_check", str(path), "--fps", "50"], text=True, capture_output=True, check=False)
            self.assertEqual(process.returncode, expected)
            self.assertIn(json.loads(process.stdout)["status"], ("pass", "fail", "invalid"))
            self.assertEqual(process.stderr, "")


if __name__ == "__main__":
    unittest.main()
