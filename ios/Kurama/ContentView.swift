import SwiftUI

struct ContentView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        Group {
            if model.connection == nil {
                SetupView()
            } else {
                FoxScreen(talker: model.talker)
            }
        }
    }
}

/// The main screen: sky, grass, the fox, speech bubbles and the talk controls.
struct FoxScreen: View {
    @EnvironmentObject var model: AppModel
    @ObservedObject var talker: Talker  // so the screen updates as the conversation changes
    @StateObject private var stage = Stage()
    @State private var typed = ""
    @FocusState private var typing: Bool

    var body: some View {
        GeometryReader { geo in
            let foxWidth = min(geo.size.width * 0.78, 360)
            ZStack(alignment: .topLeading) {
                LinearGradient(colors: [Color(red: 0.75, green: 0.89, blue: 0.95),
                                        Color(red: 0.92, green: 0.96, blue: 0.94)],
                               startPoint: .top, endPoint: .bottom)
                    .ignoresSafeArea()
                Rectangle()
                    .fill(Color(red: 0.81, green: 0.90, blue: 0.75))
                    .frame(height: geo.size.height * 0.30)
                    .overlay(alignment: .top) { Rectangle().fill(Color(red: 0.71, green: 0.84, blue: 0.64)).frame(height: 3) }
                    .frame(maxHeight: .infinity, alignment: .bottom)
                    .ignoresSafeArea(edges: .bottom)

                if let animations = model.animations {
                    let height = foxWidth * animations.height / animations.width
                    FoxCanvas(animations: animations, pictures: model.pictures, stage: stage)
                        .frame(width: foxWidth, height: height)
                        .scaleEffect(x: stage.faceRight ? -1 : 1, y: 1)
                        .offset(x: stage.x, y: geo.size.height * 0.70 - height + 12)
                        .onTapGesture { talk() }
                        .onAppear {
                            stage.foxWidth = foxWidth
                            stage.screenWidth = geo.size.width
                            stage.start()
                        }
                } else {
                    ProgressView("Waking Kurama…")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }

                VStack(spacing: 12) {
                    Text(talker.status)
                        .font(.subheadline)
                        .padding(.horizontal, 14).padding(.vertical, 6)
                        .background(talker.mode == .listening ? Color.green : Color.white.opacity(0.92),
                                    in: Capsule())
                        .foregroundColor(talker.mode == .listening ? .white : .secondary)
                    if !talker.heard.isEmpty || !talker.reply.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            if !talker.heard.isEmpty {
                                Text("You: \(talker.heard)").font(.footnote).foregroundColor(.secondary)
                            }
                            if !talker.reply.isEmpty {
                                Text(talker.reply).font(.body)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(14)
                        .background(Color.white.opacity(0.92), in: RoundedRectangle(cornerRadius: 18))
                        .padding(.horizontal, 16)
                    }
                    Spacer()
                    HStack(spacing: 10) {
                        TextField("Type a message…", text: $typed)
                            .focused($typing)
                            .submitLabel(.send)
                            .onSubmit(sendTyped)
                            .padding(.horizontal, 16).frame(height: 48)
                            .background(Color.white, in: Capsule())
                        Button(action: talk) {
                            Image(systemName: talker.mode == .listening ? "waveform" : "mic.fill")
                                .font(.title2)
                                .foregroundColor(.white)
                                .frame(width: 56, height: 56)
                                .background(talker.mode == .listening ? Color.green : Color.orange, in: Circle())
                        }
                        .accessibilityLabel("Talk to Kurama")
                    }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 8)
                }
                .padding(.top, 8)
            }
        }
        .onReceive(talker.$mode) { stage.conversation = $0 }
        .onReceive(talker.$activity) { activity in
            guard let activity else { return }
            stage.act(activity)
            DispatchQueue.main.async { talker.activity = nil }
        }
        .onReceive(model.$talkNow) { now in
            if now { model.talkNow = false; talk() }
        }
    }

    private func talk() {
        typing = false
        stage.wakeUp()
        talker.toggle()
    }

    private func sendTyped() {
        let text = typed
        typed = ""
        stage.wakeUp()
        Task { await talker.send(text) }
    }
}

/// Draws the current frame of the fox.
struct FoxCanvas: View {
    let animations: Animations
    let pictures: PictureBox
    @ObservedObject var stage: Stage

    var body: some View {
        TimelineView(.animation) { timeline in  // redraws in step with the screen
            Canvas { context, size in
                let seconds = timeline.date.timeIntervalSince(stage.animStart)
                let ops = animations.frame(stage.anim, at: seconds)
                FrameRenderer.draw(ops, in: context, scale: size.width / animations.width, pictures: pictures)
            }
        }
    }
}

/// Shown until the phone is connected to Groot on the Mac.
struct SetupView: View {
    @EnvironmentObject var model: AppModel
    @State private var link = ""

    var body: some View {
        VStack(spacing: 18) {
            Image(uiImage: UIImage(named: "red-white-fox-sleeping") ?? UIImage())
                .resizable().scaledToFit().frame(height: 150)
            Text("Connect Kurama to your Mac").font(.title2.bold())
            Text("On your Mac run:\n**python -m groot --phone**\nthen scan the **app QR code** with your iPhone camera. Or paste the link here:")
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
            TextField("kurama://connect?… or http://…/?k=…", text: $link)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .padding(12)
                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12))
            Button("Connect") {
                if let url = URL(string: link.trimmingCharacters(in: .whitespacesAndNewlines)) {
                    model.open(url)
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(.orange)
            if let problem = model.problem {
                Text(problem).foregroundColor(.red).multilineTextAlignment(.center)
            }
        }
        .padding(24)
    }
}
