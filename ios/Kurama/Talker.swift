import AVFoundation
import Speech
import SwiftUI

/// Listening, thinking and speaking: a conversation with Groot on the Mac.
@MainActor
final class Talker: NSObject, ObservableObject, AVAudioPlayerDelegate, AVSpeechSynthesizerDelegate {
    enum Mode { case idle, listening, thinking, speaking }

    @Published var mode: Mode = .idle
    @Published var heard = ""
    @Published var reply = ""
    @Published var status = "Tap me to wake me up"
    /// Set when Groot asks the fox to do something (dance, jump, wave, sleep...).
    @Published var activity: String?

    var connection: Connection?
    private var talking = false  // keep listening after each answer until you say "stop"
    private let recognizer = SFSpeechRecognizer()
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var silenceTimer: Timer?
    private var player: AVAudioPlayer?
    private let synthesizer = AVSpeechSynthesizer()
    private var afterSpeaking: (() -> Void)?
    private var latestHeard = ""  // what speech recognition has heard so far

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    // MARK: - start / stop

    func toggle() {
        if talking || mode != .idle { stop(); return }
        talking = true
        Task { await listen() }
    }

    func stop(_ message: String = "Tap me to talk") {
        talking = false
        stopListening()
        player?.stop()
        synthesizer.stopSpeaking(at: .immediate)
        mode = .idle
        status = message
    }

    // MARK: - listening

    private func permissions() async -> Bool {
        let speech = await withCheckedContinuation { done in
            SFSpeechRecognizer.requestAuthorization { done.resume(returning: $0 == .authorized) }
        }
        let mic = await withCheckedContinuation { done in
            AVAudioApplication.requestRecordPermission { done.resume(returning: $0) }
        }
        return speech && mic
    }

    func listen() async {
        guard talking else { return }
        guard await permissions() else {
            stop("Please allow the microphone and speech recognition in Settings")
            return
        }
        guard let recognizer, recognizer.isAvailable else {
            stop("Speech recognition isn't available right now")
            return
        }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetooth])
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let request = SFSpeechAudioBufferRecognitionRequest()
            request.shouldReportPartialResults = true
            self.request = request
            let input = engine.inputNode
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { buffer, _ in
                request.append(buffer)
            }
            engine.prepare()
            try engine.start()
        } catch {
            stop("I couldn't use the microphone")
            return
        }

        heard = ""
        latestHeard = ""
        mode = .listening
        status = "Listening…"
        guard let request = self.request else { stop(); return }
        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            let text = result?.bestTranscription.formattedString
            let isFinal = result?.isFinal ?? false
            let failed = error != nil
            Task { @MainActor in
                guard let self else { return }
                if let text {
                    self.latestHeard = text
                    self.heard = text
                    self.waitForSilence { self.finishListening() }
                    if isFinal { self.finishListening() }
                } else if failed {
                    self.finishListening()
                }
            }
        }
        // nobody spoke for a while: go back to waiting
        waitForSilence(seconds: 8) { [weak self] in self?.finishListening() }
    }

    /// You've stopped talking once there's been a short silence.
    private func waitForSilence(seconds: TimeInterval = 1.3, then: @escaping @MainActor () -> Void) {
        silenceTimer?.invalidate()
        silenceTimer = Timer.scheduledTimer(withTimeInterval: seconds, repeats: false) { _ in
            MainActor.assumeIsolated { then() }  // scheduled timers fire on the main thread
        }
    }

    private func stopListening() {
        silenceTimer?.invalidate()
        silenceTimer = nil
        if engine.isRunning {
            engine.stop()
            engine.inputNode.removeTap(onBus: 0)
        }
        request?.endAudio()
        task?.cancel()
        request = nil
        task = nil
    }

    private func finishListening() {
        guard mode == .listening else { return }
        stopListening()
        let spoken = latestHeard.trimmingCharacters(in: .whitespacesAndNewlines)
        if spoken.isEmpty { stop(); return }
        Task { await send(spoken, fromVoice: true) }
    }

    // MARK: - asking Groot

    func send(_ text: String, fromVoice: Bool = false) async {
        guard let connection else { return }
        if !fromVoice { talking = false }
        heard = text
        reply = "…"
        mode = .thinking
        status = "Thinking…"
        do {
            let answer = try await connection.chat(text)
            reply = answer.text
            activity = answer.activity
            await speak(answer) { [weak self] in
                guard let self else { return }
                if answer.end || !self.talking { self.stop() } else { Task { await self.listen() } }
            }
        } catch Connection.Problem.wrongKey {
            reply = "The secret key doesn't match. Scan the QR code from your Mac again."
            stop()
        } catch {
            reply = "I can't reach your Mac. Is Groot running there (python -m groot --phone)?"
            stop()
        }
    }

    // MARK: - speaking

    private func speak(_ answer: Connection.Reply, then done: @escaping () -> Void) async {
        mode = .speaking
        status = "Speaking…"
        afterSpeaking = done
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
        if let id = answer.audioID, let connection, let data = try? await connection.audio(id),
           let player = try? AVAudioPlayer(data: data) {
            self.player = player
            player.delegate = self
            if player.play() { return }
        }
        guard !answer.say.isEmpty else { finishedSpeaking(); return }
        synthesizer.speak(AVSpeechUtterance(string: answer.say))  // the phone's own voice as a fallback
    }

    private func finishedSpeaking() {
        let next = afterSpeaking
        afterSpeaking = nil
        if mode == .speaking { next?() }
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in self.finishedSpeaking() }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in self.finishedSpeaking() }
    }
}
