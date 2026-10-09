import Foundation

/// Where Groot is running on the Mac, and the secret key that lets this phone use it.
/// Saved on the phone after you scan the QR code once.
struct Connection: Equatable {
    var server: URL
    var key: String

    private static let serverKey = "kurama.server"
    private static let keyKey = "kurama.key"

    static func load() -> Connection? {
        let defaults = UserDefaults.standard
        guard let text = defaults.string(forKey: serverKey), let url = URL(string: text),
              let key = defaults.string(forKey: keyKey), !key.isEmpty else { return nil }
        return Connection(server: url, key: key)
    }

    func save() {
        UserDefaults.standard.set(server.absoluteString, forKey: Self.serverKey)
        UserDefaults.standard.set(key, forKey: Self.keyKey)
    }

    static func forget() {
        UserDefaults.standard.removeObject(forKey: serverKey)
        UserDefaults.standard.removeObject(forKey: keyKey)
    }

    /// Understands both the app link  kurama://connect?server=http://...&k=KEY
    /// and the plain web link  http(s)://host:port/?k=KEY  shown by `python -m groot --phone`.
    static func from(_ url: URL) -> Connection? {
        guard let parts = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        let items = parts.queryItems ?? []
        guard let key = items.first(where: { $0.name == "k" })?.value, !key.isEmpty else { return nil }
        if url.scheme == "kurama" {
            guard let server = items.first(where: { $0.name == "server" })?.value,
                  let serverURL = URL(string: server) else { return nil }
            return Connection(server: serverURL, key: key)
        }
        guard let scheme = parts.scheme, scheme.hasPrefix("http"), let host = parts.host else { return nil }
        var base = URLComponents()
        base.scheme = scheme
        base.host = host
        base.port = parts.port
        guard let server = base.url else { return nil }
        return Connection(server: server, key: key)
    }

    // MARK: - talking to the Mac

    struct Reply {
        var text: String
        var say: String
        var end: Bool
        var activity: String?
        var audioID: String?
    }

    enum Problem: Error { case wrongKey, unreachable, bad }

    private func request(_ path: String) -> URLRequest {
        var request = URLRequest(url: server.appendingPathComponent(path))
        request.setValue(key, forHTTPHeaderField: "X-Groot-Key")
        request.timeoutInterval = 60
        return request
    }

    private func data(for request: URLRequest) async throws -> Data {
        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            throw Problem.unreachable
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 401 { throw Problem.wrongKey }
        guard status == 200 else { throw Problem.bad }
        return data
    }

    func frames() async throws -> Data {
        try await data(for: request("api/frames"))
    }

    func picture(_ name: String) async throws -> Data {
        try await data(for: request("api/asset/\(name)"))
    }

    func audio(_ id: String) async throws -> Data {
        try await data(for: request("api/audio/\(id)"))
    }

    func chat(_ text: String) async throws -> Reply {
        var req = request("api/chat")
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["text": text])
        let body = try await data(for: req)
        guard let json = try JSONSerialization.jsonObject(with: body) as? [String: Any] else { throw Problem.bad }
        return Reply(text: json["reply"] as? String ?? "",
                     say: json["say"] as? String ?? "",
                     end: json["end"] as? Bool ?? false,
                     activity: json["activity"] as? String,
                     audioID: json["audio"] as? String)
    }
}

/// Keeps a copy of the fox's animations and pictures on the phone,
/// so Kurama still shows up (sleeping) when the Mac is off.
enum Cache {
    static var folder: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let url = base.appendingPathComponent("Kurama", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    static func read(_ name: String) -> Data? {
        try? Data(contentsOf: folder.appendingPathComponent(name))
    }

    static func write(_ data: Data, _ name: String) {
        try? data.write(to: folder.appendingPathComponent(name), options: .atomic)
    }
}
