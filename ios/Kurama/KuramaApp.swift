import SwiftUI

@main
struct KuramaApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .onOpenURL { model.open($0) }  // kurama://connect?... from the QR code, kurama://talk from the widget
                .task { await model.loadAnimations() }
        }
    }
}

/// Everything the app shares between screens.
@MainActor
final class AppModel: ObservableObject {
    @Published var connection: Connection? = Connection.load()
    @Published var animations: Animations?
    @Published var problem: String?
    @Published var talkNow = false  // the widget asked to start talking
    let talker = Talker()
    let pictures = PictureBox()

    init() {
        talker.connection = connection
    }

    func open(_ url: URL) {
        if url.scheme == "kurama", url.host == "talk" {
            talkNow = true
            return
        }
        guard let found = Connection.from(url) else {
            problem = "That link doesn't look right. Use the link or QR code shown on your Mac."
            return
        }
        found.save()
        connection = found
        talker.connection = found
        problem = nil
        Task { await loadAnimations() }
    }

    /// The fox's animations and pictures: from the Mac when it's reachable,
    /// otherwise the copy saved on the phone last time.
    func loadAnimations() async {
        guard let connection else { return }
        var data = try? await connection.frames()
        if let data { Cache.write(data, "frames.json") } else { data = Cache.read("frames.json") }
        guard let data, let parsed = Animations(json: data) else {
            problem = "Can't reach Groot on your Mac yet. Start it with: python -m groot --phone"
            return
        }
        for name in parsed.pictureNames where !pictures.names.contains(name) {
            var picture = try? await connection.picture(name)
            if let picture { Cache.write(picture, name) } else { picture = Cache.read(name) }
            if let picture { pictures.add(name, data: picture) }
        }
        animations = parsed
    }
}
