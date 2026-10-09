import SwiftUI

/// Kurama's little life on the screen, the same routine as on the Mac:
/// sleep curled up in a corner, wake up when called, wander a bit,
/// and walk back to the corner to sleep when the conversation is over.
@MainActor
final class Stage: ObservableObject {
    enum Routine { case sleep, awake, returning }

    @Published var anim = "sleep"
    @Published var x: CGFloat = 0          // left edge of the fox, in points
    @Published var faceRight = false
    /// What the conversation is doing; set by the screen, read every frame.
    var conversation: Talker.Mode = .idle

    var foxWidth: CGFloat = 300
    var screenWidth: CGFloat = 390
    private(set) var animStart = Date()
    private var routine = Routine.sleep
    private var corner = "right"
    private var awakeSince = Date()
    private var nextWander = Date()
    private var target: CGFloat?
    private var activityUntil = Date.distantPast
    private var timer: Timer?
    private var last = Date()
    private let awakeBeforeSleep: TimeInterval = 20

    func start() {
        x = cornerX(corner)
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.step() }
        }
    }

    func cornerX(_ side: String) -> CGFloat {
        side == "left" ? -foxWidth * 0.08 : screenWidth - foxWidth * 0.92
    }

    private func nearestCorner() -> String {
        abs(x - cornerX("left")) < abs(x - cornerX("right")) ? "left" : "right"
    }

    private func play(_ name: String) {
        if anim != name { anim = name; animStart = Date() }
    }

    func wakeUp() {
        if routine != .awake { routine = .awake; target = nil }
        awakeSince = Date()
    }

    /// Something Groot asked the fox to do.
    func act(_ activity: String?) {
        guard let activity, activity != "stop" else { return }
        if activity == "sleep" {
            corner = nearestCorner(); routine = .returning; target = cornerX(corner)
            return
        }
        let seconds: [String: Double] = ["dance": 4, "jump": 2, "wave": 3, "run": 3]
        let name = ["football": "dance", "butterfly": "dance", "run": "walk"][activity] ?? activity
        wakeUp()
        play(name)
        activityUntil = Date().addingTimeInterval(seconds[activity] ?? 4)
    }

    /// One frame of the routine (30 times a second).
    func step() {
        let now = Date()
        let dt = min(0.1, now.timeIntervalSince(last))
        last = now
        if now < activityUntil { return }
        switch conversation {
        case .listening: wakeUp(); return play("listening")
        case .thinking: wakeUp(); return play("thinking")
        case .speaking: wakeUp(); return play("speaking")
        case .idle: break
        }
        if routine == .sleep {
            x = cornerX(corner)
            faceRight = corner == "left"  // face into the screen from the corner
            return play("sleep")
        }
        if let goal = target {  // walking: back to bed, or just wandering
            let dx = goal - x, speed = 80 * dt
            if abs(dx) > speed {
                x += dx > 0 ? speed : -speed
                faceRight = dx > 0
                return play("walk")
            }
            x = goal
            target = nil
            if routine == .returning { routine = .sleep; return play("sleep") }
        }
        if now.timeIntervalSince(awakeSince) > awakeBeforeSleep {  // nothing to do: back to bed
            corner = nearestCorner()
            routine = .returning
            target = cornerX(corner)
            return play("walk")
        }
        if now > nextWander {  // stretch the legs now and then
            nextWander = now.addingTimeInterval(7 + Double.random(in: 0...8))
            if Bool.random() {
                target = cornerX("left") + CGFloat.random(in: 0...1) * (cornerX("right") - cornerX("left"))
            }
        }
        play("idle")
    }

    var isAsleep: Bool { routine == .sleep }
}
