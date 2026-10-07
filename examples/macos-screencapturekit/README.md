# ScreenCaptureKit timestamp example

This macOS 15+ example captures its own animated 640×360 calibration window and
exports a CSV for capture-check. It selects that window by both window ID and
process ID; it offers no arbitrary window or display selection. Only scalar
timestamps are retained. Images and audio are not saved.

## Build and test

Run from the repository root with Xcode 16+ or matching Command Line Tools installed:

```sh
mkdir -p build/macos-screencapturekit
xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macosx15.0" \
  examples/macos-screencapturekit/Timing.swift \
  examples/macos-screencapturekit/CaptureWindow.swift \
  -o build/macos-screencapturekit/capture-window
build/macos-screencapturekit/capture-window --help

xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macosx15.0" \
  examples/macos-screencapturekit/Timing.swift \
  examples/macos-screencapturekit/TimingTests.swift \
  -o build/macos-screencapturekit/timing-tests
build/macos-screencapturekit/timing-tests
```

The timing tests check options, relative timestamp precision, invalid clocks,
ordering and sample limits. They do not query permissions or start capture, and
do not verify native callback scheduling.

## Collect and analyze

The program requires existing Screen Recording access. Its preflight check exits
before content enumeration or capture if access is absent; it never requests a
permission prompt. If you choose to enable access manually in System Settings →
Privacy & Security → Screen & System Audio Recording, restart the program
afterward.

Keep the calibration window visible during the run. Defaults are a maximum of
30 fps and 5 seconds. Frame rate accepts integers from 1 to 60; duration accepts
1–60 seconds.

```sh
build/macos-screencapturekit/capture-window --fps 30 --duration 5 \
  > build/macos-screencapturekit/normal.csv && \
python3 -m capture_check build/macos-screencapturekit/normal.csv --fps 30
```

CSV goes to stdout after capture stops; diagnostics and counters go to stderr.
The command chain analyzes the file only when collection succeeds. Closing the
window or interrupting the program cancels collection without exporting CSV.

To pause the source animation for one second:

```sh
build/macos-screencapturekit/capture-window --fps 30 --duration 5 \
  --pause-at 2 --pause-for 1 > build/macos-screencapturekit/pause.csv && \
python3 -m capture_check build/macos-screencapturekit/pause.csv --fps 30
```

The pause is relative to completion of startCapture. Startup and stopping frames
may be present in the log. The pause must start after zero and end before the
requested duration.

## What the measurements mean

The CSV contains relative presentation timestamps of delivered, valid
ScreenCaptureKit frames whose status is complete. It measures their presentation
cadence, not callback arrival time or frames accepted by OBS, Unity or an encoder.
Apple's [capture sample](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-in-macos)
uses the same validity/status gate; [presentationTimeStamp](https://developer.apple.com/documentation/CoreMedia/CMSampleBuffer/presentationTimeStamp)
describes media presentation timing.

The requested frame rate is a ceiling: Apple's
[minimumFrameInterval](https://developer.apple.com/documentation/screencapturekit/scstreamconfiguration/minimumframeinterval)
throttles updates, while [idle](https://developer.apple.com/documentation/screencapturekit/scframestatus/idle)
means no new frame was generated because the display did not change. Pausing the
animation may still yield complete frames. Timestamp rows do not prove distinct
image content, and a pause does not guarantee a checker failure or demonstrate
dropped-frame detection.

In one local validation on macOS 26.7, both 5-second runs at a requested 30 fps
produced 148 complete frames. The normal run measured 29.46 fps with a maximum
interval of 37.64 ms. The paused run measured 29.44 fps with a maximum interval
of 36.48 ms and also passed the default checker limits. During its requested
one-second pause, the view counted 120 paused display ticks and **zero draws**,
yet complete-frame presentation timestamps stayed regular. Image pixels and
window decorations were not compared. These observations are not portable
cadence guarantees or acceptance thresholds.
Use stderr's frame and animation counters to interpret each run. A passing check
is a result for this timestamp sequence, not a recording-quality verdict.
