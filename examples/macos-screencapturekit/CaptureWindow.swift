import AppKit
import CoreGraphics
import CoreMedia
import QuartzCore
import ScreenCaptureKit

func diagnostic(_ text: String) {
    FileHandle.standardError.write(Data((text + "\n").utf8))
}

final class FrameSink: NSObject, SCStreamOutput, SCStreamDelegate {
    // Accessed only on the output queue, including the final drain/snapshot.
    var accepting = true
    var log = TimestampLog()
    var counts: [String: Int] = [:]
    let failure = CaptureFailure()
    var onFailure: ((String) -> Void)?

    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard accepting, failure.current == nil, type == .screen else { return }
        guard sample.isValid,
              let array = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: false)
                as? [[SCStreamFrameInfo: Any]],
              let raw = array.first?[.status] as? Int,
              let status = SCFrameStatus(rawValue: raw) else {
            counts["invalid_or_unknown", default: 0] += 1
            return
        }
        let name: String
        switch status {
        case .complete: name = "complete"
        case .idle: name = "idle"
        case .blank: name = "blank"
        case .suspended: name = "suspended"
        case .started: name = "started"
        case .stopped: name = "stopped"
        @unknown default: name = "unknown"
        }
        counts[name, default: 0] += 1
        guard status == .complete else { return }
        guard sample.imageBuffer != nil else {
            fail("A complete sample has no image buffer.")
            return
        }
        do { try log.append(sample.presentationTimeStamp) }
        catch { fail(String(describing: error)) }
    }

    private func fail(_ message: String) {
        guard failure.record(message) else { return }
        onFailure?(message)
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        // Delegate callbacks need not use the sample queue. The main actor owns shutdown.
        fail("ScreenCaptureKit stopped: \(error.localizedDescription)")
    }
}

@MainActor
final class AnimationView: NSView {
    var options = Options()
    var startTime: Double?
    private var position = 0.0
    private var frameCount = 0
    private(set) var pausedTicks = 0
    private(set) var draws = 0
    private(set) var pausedDraws = 0

    private var isPaused: Bool {
        guard let startTime else { return false }
        return options.isPaused(at: ProcessInfo.processInfo.systemUptime - startTime)
    }

    @objc func tick(_ link: CADisplayLink) {
        if isPaused {
            pausedTicks += 1
            return
        }
        position = ProcessInfo.processInfo.systemUptime.truncatingRemainder(dividingBy: 3) / 3
        frameCount += 1
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        draws += 1
        if isPaused { pausedDraws += 1 }
        NSColor(calibratedWhite: 0.08, alpha: 1).setFill()
        bounds.fill()
        NSColor.systemOrange.setFill()
        NSBezierPath(ovalIn: NSRect(x: 30 + position * (bounds.width - 100),
                                   y: 160, width: 40, height: 40)).fill()
        let text = "capture-check calibration\nFrame \(frameCount)\nOnly this window is measured. No images or audio are saved."
        (text as NSString).draw(at: NSPoint(x: 24, y: 50), withAttributes: [
            .font: NSFont.monospacedSystemFont(ofSize: 14, weight: .regular),
            .foregroundColor: NSColor.white
        ])
    }

    var summary: String {
        "Animation: updates=\(frameCount), draws=\(draws), paused_ticks=\(pausedTicks), paused_draws=\(pausedDraws)"
    }
}

@MainActor
final class CalibrationApp: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let options: Options
    let queue = DispatchQueue(label: "capture-check.frames")
    let sink = FrameSink()
    var window: NSWindow!
    var view: AnimationView!
    var displayLink: CADisplayLink?
    var session: Task<Void, Never>?
    var signalSources: [DispatchSourceSignal] = []
    var cancellationReason: String?
    var finished = false
    var exitCode: Int32 = 1

    init(options: Options) { self.options = options }

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 640, height: 360),
                          styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "capture-check calibration"
        window.isReleasedWhenClosed = false
        window.delegate = self
        view = AnimationView(frame: NSRect(x: 0, y: 0, width: 640, height: 360))
        view.options = options
        window.contentView = view
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        displayLink = view.displayLink(target: view!, selector: #selector(AnimationView.tick(_:)))
        displayLink?.add(to: .main, forMode: .common)

        sink.onFailure = { [weak self] message in
            DispatchQueue.main.async { self?.cancel(message) }
        }
        for number in [SIGINT, SIGTERM] {
            signal(number, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: number, queue: .main)
            source.setEventHandler { [weak self] in self?.cancel("Interrupted; no CSV was written.") }
            source.resume()
            signalSources.append(source)
        }
        session = Task { await capture() }
    }

    func cancel(_ reason: String) {
        guard !finished else { return }
        if cancellationReason == nil { cancellationReason = reason }
        session?.cancel()
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        cancel("Calibration window closed before capture completed; no CSV was written.")
        return false // Keep the target alive until the stream has stopped.
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if finished { return .terminateNow }
        cancel("Application quit before capture completed; no CSV was written.")
        return .terminateCancel
    }

    private func capture() async {
        var stream: SCStream?
        var startAttempted = false
        var errorMessage: String?
        do {
            let ownID = CGWindowID(window.windowNumber)
            let ownPID = ProcessInfo.processInfo.processIdentifier
            // main's non-prompting permission check happens before this first enumeration.
            let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
            try Task.checkCancellation()
            guard let target = content.windows.first(where: {
                $0.windowID == ownID && $0.owningApplication?.processID == ownPID
            }) else {
                throw ExampleError("The exact calibration window was not found. No fallback capture is allowed.")
            }
            let config = SCStreamConfiguration()
            config.width = 640
            config.height = 360
            config.minimumFrameInterval = CMTime(value: 1, timescale: CMTimeScale(options.fps))
            config.showsCursor = false
            config.capturesAudio = false
            config.captureMicrophone = false
            let captureStream = SCStream(filter: SCContentFilter(desktopIndependentWindow: target),
                                         configuration: config, delegate: sink)
            stream = captureStream
            try captureStream.addStreamOutput(sink, type: .screen, sampleHandlerQueue: queue)
            startAttempted = true
            try await captureStream.startCapture()
            try Task.checkCancellation()
            view.startTime = ProcessInfo.processInfo.systemUptime
            diagnostic("Measuring only the calibration window for \(options.duration)s at up to \(options.fps) fps.")
            try await Task.sleep(nanoseconds: UInt64(options.duration * 1_000_000_000))
        } catch {
            errorMessage = cancellationReason ?? String(describing: error)
        }

        // Always stop before draining the serial callback queue and exporting scalar data.
        if startAttempted, let stream {
            do { try await stream.stopCapture() }
            catch { errorMessage = errorMessage ?? "Could not stop capture cleanly: \(error.localizedDescription)" }
        }
        displayLink?.invalidate()
        let snapshot = queue.sync { () -> (TimestampLog, [String: Int], String?) in
            sink.accepting = false
            return (sink.log, sink.counts, sink.failure.current)
        }
        let counts = snapshot.1.sorted { $0.key < $1.key }.map { "\($0.key)=\($0.value)" }.joined(separator: ", ")
        diagnostic("Frame statuses: \(counts.isEmpty ? "none" : counts)")
        diagnostic(view.summary)
        diagnostic("Metric: presentation cadence of delivered complete ScreenCaptureKit frames. Idle content can create gaps; this is not a dropped-frame or recording-quality verdict.")
        if let pauseAt = options.pauseAt {
            diagnostic("Requested animation pause: \(pauseAt)s for \(options.pauseFor)s after capture startup. ScreenCaptureKit may still deliver complete frames of unchanged content; no timestamp gap is guaranteed.")
        }
        errorMessage = errorMessage ?? cancellationReason ?? snapshot.2
        do {
            if let errorMessage { throw ExampleError(errorMessage) }
            let csv = try snapshot.0.csv()
            try FileHandle.standardOutput.write(contentsOf: Data(csv.utf8))
            exitCode = 0
        } catch {
            diagnostic("Error: \(error)")
        }
        finished = true
        signalSources.forEach { $0.cancel() }
        window.orderOut(nil)
        NSApp.stop(nil)
        // Wake the run loop so run() returns and main can use the capture exit code.
        if let event = NSEvent.otherEvent(with: .applicationDefined, location: .zero,
                                         modifierFlags: [], timestamp: 0, windowNumber: 0,
                                         context: nil, subtype: 0, data1: 0, data2: 0) {
            NSApp.postEvent(event, atStart: false)
        }
    }
}

@main
enum CaptureWindow {
    @MainActor
    static func main() {
        let arguments = Array(CommandLine.arguments.dropFirst())
        if arguments == ["--help"] {
            print("""
            Usage: capture-window [--fps 1..60] [--duration 1..60]
                                  [--pause-at SECONDS [--pause-for SECONDS]]

            Capture only this program's animated 640x360 calibration window.
            Defaults: 30 fps maximum, 5 seconds. Optional pause defaults to 1 second.
            Writes timestamp CSV to stdout only after stopping; diagnostics go to stderr.
            Requires macOS 15+ and existing Screen Recording access. Never prompts for access.
            No images or audio are saved. Idle content can cause legitimate timestamp gaps.
            """)
            exit(0)
        }
        do {
            let options = try Options.parse(arguments)
            guard CGPreflightScreenCaptureAccess() else {
                throw ExampleError("Screen Recording access is absent. No capture was started and no permission prompt was requested. If you choose to enable access manually in System Settings > Privacy & Security > Screen & System Audio Recording, restart this program afterward. See the example README.")
            }
            let application = NSApplication.shared
            application.setActivationPolicy(.regular)
            let delegate = CalibrationApp(options: options)
            application.delegate = delegate
            application.run()
            exit(delegate.exitCode)
        } catch {
            diagnostic("Error: \(error)")
            exit(2)
        }
    }
}
