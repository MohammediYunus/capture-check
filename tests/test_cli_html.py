import html
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HtmlCliTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name)

    def fixture(self, content="timestamp\n0\n0.02\n", name="timestamps.csv"):
        path = self.directory / name
        path.write_text(content, encoding="utf-8")
        return path

    def run_cli(self, source, *options):
        return subprocess.run(
            [sys.executable, "-m", "capture_check", str(source), *options],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )

    def assert_invalid(self, process, message=None):
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stderr, "")
        result = json.loads(process.stdout)
        self.assertEqual(result["status"], "invalid")
        if message is not None:
            self.assertIn(message, result["error"])

    def test_reports_preserve_json_and_exit_status(self):
        for name, fps, code in (
            ("steady-60.csv", 60, 0),
            ("stall-60.jsonl", 60, 1),
            ("portty/frames.csv", 30, 0),
        ):
            with self.subTest(fixture=name):
                source = ROOT / "examples" / name
                destination = self.directory / (source.stem + ".html")
                baseline = self.run_cli(source, "--fps", str(fps))
                process = self.run_cli(source, "--fps", str(fps), "--html", str(destination))
                self.assertEqual(process.returncode, code)
                self.assertEqual(process.stdout, baseline.stdout)
                self.assertEqual(process.stderr, baseline.stderr)
                self.assertEqual(process.stderr, "")
                self.assertIn("<html", destination.read_text(encoding="utf-8").lower())

    def test_no_html_does_not_require_renderer_module(self):
        standalone = self.directory / "capture_check.py"
        shutil.copyfile(ROOT / "capture_check.py", standalone)
        source = self.fixture()
        process = subprocess.run(
            [sys.executable, "-I", str(standalone), str(source), "--fps", "50"],
            cwd=self.directory, text=True, capture_output=True, check=False,
        )
        baseline = self.run_cli(source, "--fps", "50")
        self.assertEqual(process.returncode, 0)
        self.assertEqual(process.stdout, baseline.stdout)
        self.assertEqual(process.stderr, "")

    def test_invalid_input_or_arguments_leave_no_report(self):
        for content, options in (
            ("timestamp\n0\n0\n", ["--fps", "50"]),
            ("timestamp\n0\n0.02\n", ["--fps", "oops"]),
        ):
            with self.subTest(content=content, options=options):
                source = self.fixture(content)
                destination = self.directory / "invalid.html"
                process = self.run_cli(source, *options, "--html", str(destination))
                self.assert_invalid(process)
                self.assertFalse(destination.exists())
                destination.write_bytes(b"existing report")
                process = self.run_cli(source, *options, "--html", str(destination))
                self.assert_invalid(process)
                self.assertEqual(destination.read_bytes(), b"existing report")
                destination.unlink()

    def test_existing_report_and_input_are_preserved(self):
        source = self.fixture()
        report = self.directory / "report.html"
        report.write_bytes(b"existing report")
        source_bytes = source.read_bytes()
        for destination in (report, source):
            with self.subTest(destination=destination):
                original = destination.read_bytes()
                process = self.run_cli(source, "--fps", "50", "--html", str(destination))
                self.assert_invalid(process, "cannot write HTML report")
                self.assertEqual(destination.read_bytes(), original)
                self.assertEqual(source.read_bytes(), source_bytes)

    def test_symlink_output_preserves_input(self):
        source = self.fixture()
        destination = self.directory / "alias.html"
        try:
            destination.symlink_to(source)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")
        original = source.read_bytes()
        process = self.run_cli(source, "--fps", "50", "--html", str(destination))
        self.assert_invalid(process, "cannot write HTML report")
        self.assertTrue(destination.is_symlink())
        self.assertEqual(source.read_bytes(), original)

    def test_hardlink_output_preserves_input(self):
        source = self.fixture()
        destination = self.directory / "alias.html"
        try:
            destination.hardlink_to(source)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"hardlinks unavailable: {error}")
        original = source.read_bytes()
        process = self.run_cli(source, "--fps", "50", "--html", str(destination))
        self.assert_invalid(process, "cannot write HTML report")
        self.assertTrue(destination.samefile(source))
        self.assertEqual(source.read_bytes(), original)

    def test_missing_parent_and_directory_output_fail_cleanly(self):
        source = self.fixture()
        for destination in (self.directory / "missing" / "report.html", self.directory):
            with self.subTest(destination=destination):
                process = self.run_cli(source, "--fps", "50", "--html", str(destination))
                self.assert_invalid(process, "cannot write HTML report")
        self.assertFalse((self.directory / "missing").exists())
        self.assertTrue(self.directory.is_dir())

    def test_unicode_write_error_removes_new_report(self):
        source = self.fixture()
        destination = self.directory / "report.html"
        program = """
import runpy
import sys
import types
sys.modules['capture_check_report'] = types.SimpleNamespace(
    render_html=lambda *args, **kwargs: 'report with an unencodable \\ud800'
)
sys.argv = ['capture_check', *sys.argv[1:]]
runpy.run_module('capture_check', run_name='__main__')
"""
        process = subprocess.run(
            [sys.executable, "-c", program, str(source), "--fps", "50", "--html", str(destination)],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assert_invalid(process, "cannot write HTML report")
        self.assertFalse(destination.exists())

    def test_partial_write_failure_removes_new_report(self):
        source = self.fixture()
        destination = self.directory / "report.html"
        program = """
import runpy
import sys
import types
from pathlib import Path
real_open = Path.open
class FailingOutput:
    def __init__(self, stream):
        self.stream = stream
    def __enter__(self):
        return self
    def write(self, document):
        self.stream.write('partial report')
        self.stream.flush()
        raise OSError('simulated write failure')
    def __exit__(self, *args):
        self.stream.close()
def open_output(path, *args, **kwargs):
    stream = real_open(path, *args, **kwargs)
    return FailingOutput(stream) if args and args[0] == 'x' else stream
Path.open = open_output
sys.modules['capture_check_report'] = types.SimpleNamespace(
    render_html=lambda *args, **kwargs: 'complete report'
)
sys.argv = ['capture_check', *sys.argv[1:]]
runpy.run_module('capture_check', run_name='__main__')
"""
        process = subprocess.run(
            [sys.executable, "-c", program, str(source), "--fps", "50", "--html", str(destination)],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assert_invalid(process, "cannot write HTML report: simulated write failure")
        self.assertFalse(destination.exists())

    def test_custom_field_and_source_name_are_passed_as_text(self):
        field = "<img src=x onerror=alert(1)>&"
        name = "capture & 'quoted'.jsonl"
        source = self.fixture(
            "\n".join(json.dumps({field: value, "unused": "private metadata"})
                      for value in (1000, 1020, 1040)) + "\n",
            name=name,
        )
        destination = self.directory / "report.html"
        options = ["--fps", "50", "--field", field, "--unit", "milliseconds"]
        baseline = self.run_cli(source, *options)
        process = self.run_cli(source, *options, "--html", str(destination))
        self.assertEqual(process.returncode, 0)
        self.assertEqual(process.stdout, baseline.stdout)
        self.assertEqual(process.stderr, "")
        document = destination.read_text(encoding="utf-8")
        self.assertIn(html.escape(name, quote=True), document)
        self.assertIn(html.escape(field, quote=True), document)
        self.assertNotIn("private metadata", document)
        self.assertNotIn(str(self.directory), document)


if __name__ == "__main__":
    unittest.main()
