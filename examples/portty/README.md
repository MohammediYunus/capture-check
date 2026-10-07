# A real Portty recording

Try capture-check with a real recorder manifest, without installing Portty:

```sh
python3 -m capture_check examples/portty/frames.csv --fps 30
```

Run this from the capture-check checkout. The original **frames.csv** is unchanged
from a local Portty recording. Its **index** and **filename** columns are preserved
and ignored by capture-check. The referenced QOI images are not included.

With capture-check 0.2.0 and default limits, this sample returns exit code 0:

| Measurement | Result |
| --- | --- |
| Timestamps | 314 |
| Time between first and last sample | 10.323 s |
| Observed cadence | 30.32 samples/s |
| Median / p95 / maximum interval | 33 / 41 / 47 ms |
| Intervals above the target interval | 134 |
| Intervals above the maximum-gap limit | 0 |

The 134 intervals above 33.33 ms are not a count of dropped frames. The default
limits check overall cadence and the longest gap; this recording passes both.

## What was recorded?

[record.script](record.script) displays generated text in Portty's demo mode,
with quiet periods before and after 12 text updates. It does not start a shell
inside Portty or capture other applications.

A separate local image audit found all 314 referenced QOI files present and
decodable at 950 × 370 pixels. There were 13 distinct images and 12 changes
between adjacent images, matching the scripted updates. The other 301 adjacent
pairs were equal because the content deliberately stayed still between updates.

That image audit is separate from capture-check. A regular stream of timestamps
does not establish how often the picture changes. Portty also advances its
manifest when an image read or write fails, so the CSV alone cannot establish
whether the referenced images exist.

## Record your own sample

You need a working **portty** command on your PATH. From the capture-check checkout:

```sh
capture_demo_dir=$(mktemp -d)
cp examples/portty/record.script "$capture_demo_dir/record.script"
: > "$capture_demo_dir/portty.conf"
(
  cd "$capture_demo_dir"
  portty -g 50x10 -d "Owned recorder calibration content" -S record.script
)
python3 -m capture_check "$capture_demo_dir/frames/frames.csv" --fps 30
```

The empty local configuration keeps the example independent of your usual Portty
configuration. The script writes QOI frames and **frames.csv** into **frames/**,
saves **final.png**, then exits. It captures Portty's own renderer. No desktop
screen-recording permission is needed.

Always use a fresh output directory for one recording. Portty numbers new images
after existing ones while replacing the manifest when a recording starts. A short
relative directory name also avoids the script parser's handling of spaces in
recording paths.

The waits add up to about ten seconds of recording, but script scheduling adds
overhead. Your duration and timing results will vary. These numbers are one
integration check, not a Portty performance benchmark.

## Provenance

[provenance.json](provenance.json) records the original CSV and script hashes,
the exact capture-check report, source revisions, environment and image-audit
summary. This was a local macOS arm64 build of Portty 0.8.7 with coffer 0.6.2 and
optional ThorVG disabled.

The build used the packaging fix proposed in
[Portty PR #9](https://github.com/chestso/portty/pull/9), which was unmerged when
this recording was made. That patch changes packaging and CI only; the recorder
source is unchanged from commit 570cdd6. This is a self-run example, not evidence
of upstream adoption.
