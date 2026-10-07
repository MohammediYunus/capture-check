import CoreMedia
import Foundation

@main
enum TimingTests {
    static var checks = 0

    static func check(_ condition: @autoclosure () throws -> Bool, _ name: String) throws {
        guard try condition() else { throw ExampleError("FAIL: \(name)") }
        checks += 1
    }

    static func rejects(_ name: String, _ body: () throws -> Void) throws {
        do { try body() }
        catch { checks += 1; return }
        throw ExampleError("FAIL: expected rejection: \(name)")
    }

    static func main() throws {
        let defaults = try Options.parse([])
        try check(defaults.fps == 30 && defaults.duration == 5 && defaults.pauseAt == nil, "short defaults")
        let options = try Options.parse(["--fps", "60", "--duration", "5", "--pause-at", "2", "--pause-for", "1"])
        try check(options.fps == 60 && options.duration == 5, "configured values")
        try check(!options.isPaused(at: 1.999) && options.isPaused(at: 2)
                  && options.isPaused(at: 2.999) && !options.isPaused(at: 3), "pause boundaries")
        for args in [
            ["--fps", "0"], ["--fps", "61"], ["--fps", "30.5"],
            ["--duration", "0"], ["--duration", "61"], ["--duration", "nan"],
            ["--duration", "inf"], ["--pause-for", "1"], ["--pause-at", "0"],
            ["--pause-at", "4"], ["--pause-at", "2", "--pause-for", "-1"],
            ["--pause-at", "nan"], ["--fps"], ["--window-id", "1"],
            ["--fps", "30", "--fps", "60"]
        ] {
            try rejects(args.joined(separator: " ")) { _ = try Options.parse(args) }
        }
        try rejects("empty capture") { _ = try TimestampLog().csv() }
        var log = TimestampLog()
        // A large absolute clock must retain tiny intervals after relative subtraction.
        let base: Int64 = 9_000_000_000_000_000
        try log.append(CMTime(value: base, timescale: 60))
        try rejects("one timestamp") { _ = try log.csv() }
        try log.append(CMTime(value: base + 1, timescale: 60))
        try log.append(CMTime(value: base + 2, timescale: 60))
        let csv = try log.csv()
        let values = csv.split(separator: "\n").dropFirst().compactMap { Double($0) }
        try check(csv.hasPrefix("timestamp\n") && csv.hasSuffix("\n"), "CSV shape")
        try check(values.count == 3 && values[0] == 0
                  && abs(values[1] - 1.0 / 60) < 1e-12
                  && abs(values[2] - 2.0 / 60) < 1e-12, "relative precision")
        try rejects("duplicate timestamp") { try log.append(CMTime(value: base + 2, timescale: 60)) }
        try rejects("backwards timestamp") { try log.append(CMTime(value: base, timescale: 60)) }
        try rejects("epoch change") {
            try log.append(CMTime(value: base + 3, timescale: 60, flags: .valid, epoch: 1))
        }
        for time in [CMTime.invalid, .indefinite, .positiveInfinity, .negativeInfinity] {
            try rejects("nonnumeric timestamp") { try log.append(time) }
        }
        var bounded = TimestampLog()
        for index in 0..<TimestampLog.maximumSamples {
            try bounded.append(CMTime(value: Int64(index), timescale: 60))
        }
        try rejects("sample bound") {
            try bounded.append(CMTime(value: Int64(TimestampLog.maximumSamples), timescale: 60))
        }
        try check(log.times.count == 3, "rejected input never changes valid data")
        // Simulate a delegate error arriving off the main queue while UI shutdown
        // is still pending. Finalization must see the error without running UI work.
        let failure = CaptureFailure()
        let delegateQueue = DispatchQueue(label: "capture-check.test.delegate")
        _ = delegateQueue.sync { failure.record("stream stopped unexpectedly") }
        try check(failure.current == "stream stopped unexpectedly", "delegate failure visible before UI callback")
        try check(!failure.record("secondary shutdown error")
                  && failure.current == "stream stopped unexpectedly", "preserve first failure")
        print("\(checks) timing/option checks passed; no capture APIs called.")
    }
}
