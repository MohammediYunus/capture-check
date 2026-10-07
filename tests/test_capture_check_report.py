import math
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from capture_check import analyze, read_timestamps
from capture_check_report import MAX_PLOT_POINTS, interval_overview, longest_intervals, render_html


ROOT = Path(__file__).resolve().parents[1]


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.attributes = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)

    def handle_data(self, data):
        self.text.append(data)


class HtmlReportTests(unittest.TestCase):
    def render(self, timestamps, fps=60, **options):
        result = analyze(timestamps, fps)
        return render_html(timestamps, result, source_name="timing.csv", **options)

    def test_real_portty_fixture_keeps_above_target_counts_informational(self):
        timestamps = read_timestamps(ROOT / "examples/portty/frames.csv")
        result = analyze(timestamps, 30)
        report = render_html(timestamps, result, source_name="frames.csv")
        parsed = ReportParser()
        parsed.feed(report)
        text = " ".join(parsed.text)
        self.assertIn("passed", text)
        self.assertIn("Samples 61 → 62", text)
        self.assertIn("47 ms", text)
        self.assertIn("1.968 to 2.015 s", text)
        self.assertIn("134", text)
        self.assertIn("(informational)", text)
        self.assertIn("0 of 313", text)
        self.assertNotIn('class="over-limit"', report)
        self.assertIn('"interval_count": 313', "".join(parsed.text))

    def test_stall_fixture_shows_both_failures_and_exact_location(self):
        timestamps = read_timestamps(ROOT / "examples/stall-60.jsonl")
        report = self.render(timestamps)
        self.assertIn("Observed cadence is below the configured minimum.", report)
        self.assertIn("At least one interval exceeds the configured gap limit.", report)
        self.assertIn("Samples 5 → 6", report)
        self.assertIn("216.667 ms", report)
        self.assertIn('class="over-limit"', report)
        self.assertIn("Above limit", report)

    def test_exact_ties_keep_first_interval_and_source_order(self):
        timestamps = [0, 1, 2, 3]
        self.assertEqual(longest_intervals(timestamps), [(0, 1), (1, 1), (2, 1)])
        report = self.render(timestamps, fps=1)
        self.assertIn("Samples 1 → 2", report)
        self.assertIn("Longest 3 of 3 intervals", report)

    def test_two_samples_have_one_nonempty_interval(self):
        report = self.render([50, 50.5], fps=2)
        self.assertIn("Longest 1 of 1 intervals", report)
        self.assertIn("0.0 to 0.5 s since first sample", report)
        self.assertIn("All 1 intervals shown.", report)
        self.assertEqual(len(interval_overview([50, 50.5])), 1)

    def test_elapsed_positions_ignore_absolute_clock_origin(self):
        values = [0, 0.25, 0.5, 1.0]
        shifted = [value + 2**30 for value in values]
        self.assertEqual(self.render(values, fps=4), self.render(shifted, fps=4))

    def test_small_intervals_late_in_long_log_keep_distinct_endpoints(self):
        timestamps = [0, 10000, 10000 + 1 / 60, 10000 + 2 / 60]
        report = self.render(timestamps)
        self.assertIn('<span>10000</span> to <span>10000.016666666666 s</span>', report)
        self.assertIn('<span>10000.016666666666</span> to <span>10000.033333333333 s</span>', report)

    def test_large_log_preserves_isolated_worst_and_bounded_html(self):
        timestamps = [index / 60 for index in range(20001)]
        # A single 500 ms gap followed by normal cadence.
        timestamps[13700:] = [value + 0.5 for value in timestamps[13700:]]
        points = interval_overview(timestamps)
        self.assertLessEqual(len(points), MAX_PLOT_POINTS)
        self.assertIn(13699, [index for index, _ in points])
        self.assertEqual(longest_intervals(timestamps)[0][0], 13699)
        report = self.render(timestamps)
        self.assertIn("bucket maxima from 20,000 intervals", report)
        self.assertIn("Samples 13,700 → 13,701", report)
        self.assertIn("Longest 10 of 20,000 intervals", report)
        self.assertLess(len(report), 300_000)

    def test_sparse_time_buckets_do_not_invent_zero_measurements(self):
        timestamps = [0, 0.001, 0.002, 0.003, 1000]
        points = interval_overview(timestamps)
        self.assertEqual(len(points), 2)
        self.assertEqual(points[-1], (3, 999.997))
        self.assertTrue(all(interval > 0 for _, interval in points))

    def test_output_has_finite_geometry_for_extreme_valid_values(self):
        for timestamps, fps in (([0, 1e305, 1.0001e305], 1e-304),
                                ([0, 1e-308, 2e-308], 1e308)):
            with self.subTest(fps=fps):
                report = self.render(timestamps, fps=fps)
                coordinates = re.findall(r'(?:cx|cy)="([^"]+)"', report)
                self.assertTrue(coordinates)
                self.assertTrue(all(math.isfinite(float(value)) for value in coordinates))
                self.assertNotRegex(report, r'(?:cx|cy)="(?:inf|nan)"')

    def test_threshold_rounding_does_not_create_failed_markers(self):
        timestamps = [index / 60 for index in range(100)]
        report = self.render(timestamps)
        self.assertNotIn('class="over-limit"', report)
        self.assertNotIn("Above limit</td>", report)
        self.assertIn("floating-point tolerance", report)
        self.assertIn("Full precision measurements (JSON)", report)

    def test_near_limit_uses_same_seconds_tolerance_as_analysis(self):
        timestamps = [0, 1e-7 + 5e-13]
        result = analyze(timestamps, 2e7, min_rate_ratio=0.4)
        self.assertEqual(result["status"], "pass")
        report = render_html(timestamps, result, source_name="small.csv")
        self.assertNotIn('class="over-limit"', report)
        self.assertNotIn("Above limit</td>", report)

    def test_millisecond_roundtrip_cannot_change_gap_classification(self):
        timestamps = [0, 0.010309278360824743]
        result = analyze(timestamps, 97, min_rate_ratio=0.01, max_gap_frames=1)
        self.assertEqual(result["gaps"]["over_max_gap_limit"], 1)
        report = render_html(timestamps, result, source_name="boundary.csv")
        self.assertIn('class="over-limit"', report)
        self.assertIn("Above limit</td>", report)
        self.assertNotIn("Within limit</td>", report)

    def test_html_looking_labels_are_text_and_report_is_network_free(self):
        hostile = '<img src="https://example.invalid/tracker" onerror="alert(1)">&</script>'
        report = render_html([0, 1], analyze([0, 1], 1),
                             source_name=hostile, field=hostile, unit=hostile)
        parser = ReportParser()
        parser.feed(report)
        self.assertIn(hostile, "".join(parser.text))
        for tag in ("script", "img", "iframe", "link", "object"):
            self.assertNotIn(tag, parser.tags)
        for name, value in parser.attributes:
            self.assertFalse(name.startswith("on"))
            if name in ("src", "href"):
                self.assertTrue(value.startswith("#"), value)
        self.assertIn("default-src 'none'", report)
        self.assertNotIn("@import", report)
        self.assertNotIn("url(", report)


if __name__ == "__main__":
    unittest.main()
