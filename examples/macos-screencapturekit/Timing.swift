import CoreMedia
import Foundation

struct ExampleError: Error, CustomStringConvertible {
    let description: String
    init(_ description: String) { self.description = description }
}

// Stream error callbacks have no documented queue affinity. Record errors before
// asking the main actor to stop, so a pending UI callback cannot hide a failure.
final class CaptureFailure {
    private let lock = NSLock()
    private var message: String?

    var current: String? {
        lock.lock()
        defer { lock.unlock() }
        return message
    }

    @discardableResult
    func record(_ error: String) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard message == nil else { return false }
        message = error
        return true
    }
}

struct Options {
    var fps = 30
    var duration = 5.0
    var pauseAt: Double?
    var pauseFor = 1.0

    static func parse(_ arguments: [String]) throws -> Options {
        var options = Options()
        var seen = Set<String>()
        var index = 0
        while index < arguments.count {
            let flag = arguments[index]
            guard ["--fps", "--duration", "--pause-at", "--pause-for"].contains(flag),
                  seen.insert(flag).inserted, index + 1 < arguments.count else {
                throw ExampleError("Unknown, repeated or incomplete option: \(flag). See --help.")
            }
            let value = arguments[index + 1]
            switch flag {
            case "--fps":
                guard let fps = Int(value), (1...60).contains(fps) else {
                    throw ExampleError("--fps must be an integer from 1 to 60.")
                }
                options.fps = fps
            default:
                guard let number = Double(value), number.isFinite else {
                    throw ExampleError("\(flag) must be a finite number of seconds.")
                }
                if flag == "--duration" { options.duration = number }
                if flag == "--pause-at" { options.pauseAt = number }
                if flag == "--pause-for" { options.pauseFor = number }
            }
            index += 2
        }
        guard (1...60).contains(options.duration) else {
            throw ExampleError("--duration must be between 1 and 60 seconds.")
        }
        if let pauseAt = options.pauseAt {
            guard pauseAt > 0, options.pauseFor > 0,
                  pauseAt + options.pauseFor < options.duration else {
                throw ExampleError("The positive pause must start after 0 and end before --duration.")
            }
        } else if seen.contains("--pause-for") {
            throw ExampleError("--pause-for requires --pause-at.")
        }
        return options
    }

    func isPaused(at elapsed: Double) -> Bool {
        guard let pauseAt else { return false }
        return elapsed >= pauseAt && elapsed < pauseAt + pauseFor
    }
}

// Stores only scalar times, never sample buffers or pixels.
struct TimestampLog {
    private(set) var times: [CMTime] = []
    static let maximumSamples = 15_000

    mutating func append(_ time: CMTime) throws {
        guard time.isNumeric, CMTimeGetSeconds(time).isFinite else {
            throw ExampleError("A complete frame has an invalid/nonfinite presentation timestamp.")
        }
        guard times.count < Self.maximumSamples else {
            throw ExampleError("Sample bound exceeded; refusing an unbounded capture.")
        }
        if let previous = times.last {
            guard time.epoch == previous.epoch, CMTimeCompare(time, previous) > 0 else {
                throw ExampleError("Presentation timestamps changed epoch or did not strictly increase.")
            }
        }
        times.append(time)
    }

    func csv() throws -> String {
        guard let first = times.first, times.count >= 2 else {
            throw ExampleError("Fewer than two complete frames; insufficient data. Static content may be idle.")
        }
        var lines = ["timestamp"]
        var previous = -Double.infinity
        for time in times {
            // Subtract in CMTime before converting, to preserve small relative intervals.
            let seconds = CMTimeGetSeconds(CMTimeSubtract(time, first))
            guard seconds.isFinite, seconds > previous else {
                throw ExampleError("Relative timestamps are nonfinite or not strictly increasing.")
            }
            lines.append(String(format: "%.17g", locale: Locale(identifier: "en_US_POSIX"), seconds))
            previous = seconds
        }
        return lines.joined(separator: "\n") + "\n"
    }
}
