import SwiftUI
import UIKit

/// One drawing command, recorded on the Mac by Groot's own drawing code
/// (see groot/phone.py) and replayed here, so the phone shows the same fox.
enum DrawOp {
    case save
    case restore
    case translate(CGFloat, CGFloat)
    case rotate(Double)
    case scale(CGFloat, CGFloat)
    case clip(Path)
    case fillRect(CGRect, Color)
    case shape(Path, fill: Color?, stroke: Color?, width: CGFloat)
    case gradient(Path, start: CGPoint, end: CGPoint, stops: [Gradient.Stop], stroke: Color?, width: CGFloat)
    case text(String, at: CGPoint, size: CGFloat, color: Color, bold: Bool)
    case picture(name: String, frame: Int, columns: Int, rows: Int, rect: CGRect, opacity: Double)
}

/// All of the fox's animations: name -> frames -> drawing commands.
struct Animations {
    var width: CGFloat
    var height: CGFloat
    var fps: Double
    var every: [String: Int]
    var anims: [String: [[DrawOp]]]
    var pictureNames: Set<String>

    init?(json data: Data) {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let w = root["W"] as? Double, let h = root["H"] as? Double,
              let raw = root["anims"] as? [String: [[[Any]]]] else { return nil }
        width = CGFloat(w)
        height = CGFloat(h)
        fps = root["fps"] as? Double ?? 30
        every = root["every"] as? [String: Int] ?? [:]
        var names = Set<String>()
        var parsed: [String: [[DrawOp]]] = [:]
        for (name, frames) in raw {
            parsed[name] = frames.map { ops in
                ops.compactMap { op in
                    let decoded = Animations.decode(op)
                    if case let .picture(picture, _, _, _, _, _)? = decoded { names.insert(picture) }
                    return decoded
                }
            }
        }
        anims = parsed
        pictureNames = names
    }

    func frames(_ name: String) -> [[DrawOp]] { anims[name] ?? anims["idle"] ?? [] }

    /// Which frame to show `seconds` after an animation started.
    func frame(_ name: String, at seconds: Double) -> [DrawOp] {
        let list = frames(name)
        guard !list.isEmpty else { return [] }
        let step = Double(every[name] ?? 2)
        let index = max(0, Int(seconds * fps / step)) % list.count
        return list[index]
    }

    // MARK: - reading the recorded commands

    private static func num(_ value: Any?) -> CGFloat {
        if let n = value as? NSNumber { return CGFloat(truncating: n) }
        return 0
    }

    private static func decode(_ op: [Any]) -> DrawOp? {
        guard let kind = op.first as? String else { return nil }
        func n(_ i: Int) -> CGFloat { i < op.count ? num(op[i]) : 0 }
        func s(_ i: Int) -> String? { i < op.count ? op[i] as? String : nil }
        switch kind {
        case "S": return .save
        case "R": return .restore
        case "T": return .translate(n(1), n(2))
        case "O": return .rotate(Double(n(1)))
        case "K": return .scale(n(1), n(2))
        case "C": return .clip(path(s(1) ?? ""))
        case "F": return .fillRect(CGRect(x: n(1), y: n(2), width: n(3), height: n(4)), color(s(5)) ?? .clear)
        case "P": return .shape(path(s(1) ?? ""), fill: color(s(2)), stroke: color(s(3)), width: n(4))
        case "G":
            let stops = (op.count > 6 ? op[6] as? [[Any]] : nil)?.compactMap { stop -> Gradient.Stop? in
                guard stop.count == 2, let c = color(stop[1] as? String) else { return nil }
                return Gradient.Stop(color: c, location: num(stop[0]))
            } ?? []
            return .gradient(path(s(1) ?? ""), start: CGPoint(x: n(2), y: n(3)), end: CGPoint(x: n(4), y: n(5)),
                             stops: stops, stroke: color(s(7)), width: n(8))
        case "X":
            return .text(s(1) ?? "", at: CGPoint(x: n(2), y: n(3)), size: n(4), color: color(s(5)) ?? .black,
                         bold: (op.count > 6 ? op[6] as? Bool : nil) ?? false)
        case "I":
            return .picture(name: s(1) ?? "", frame: Int(n(2)), columns: max(1, Int(n(3))), rows: max(1, Int(n(4))),
                            rect: CGRect(x: n(5), y: n(6), width: n(7), height: n(8)), opacity: Double(n(9)))
        default: return nil
        }
    }

    /// "M x y L x y C x1 y1 x2 y2 x y Z" -> Path
    static func path(_ text: String) -> Path {
        var path = Path()
        let tokens = text.split(separator: " ")
        var i = 0
        func next() -> CGFloat {
            defer { i += 1 }
            return i < tokens.count ? CGFloat(Double(tokens[i]) ?? 0) : 0
        }
        while i < tokens.count {
            let command = tokens[i]
            i += 1
            switch command {
            case "M": path.move(to: CGPoint(x: next(), y: next()))
            case "L": path.addLine(to: CGPoint(x: next(), y: next()))
            case "C":
                let c1 = CGPoint(x: next(), y: next())
                let c2 = CGPoint(x: next(), y: next())
                path.addCurve(to: CGPoint(x: next(), y: next()), control1: c1, control2: c2)
            case "Z": path.closeSubpath()
            default: break
            }
        }
        return path
    }

    /// "#rrggbb" or "rgba(r,g,b,a)" -> Color
    static func color(_ text: String?) -> Color? {
        guard let text, !text.isEmpty else { return nil }
        if text.hasPrefix("#"), text.count == 7, let value = UInt32(text.dropFirst(), radix: 16) {
            return Color(red: Double((value >> 16) & 0xff) / 255, green: Double((value >> 8) & 0xff) / 255,
                         blue: Double(value & 0xff) / 255)
        }
        if text.hasPrefix("rgba(") {
            let numbers = text.dropFirst(5).dropLast().split(separator: ",").compactMap {
                Double($0.trimmingCharacters(in: .whitespaces))
            }
            if numbers.count == 4 {
                return Color(red: numbers[0] / 255, green: numbers[1] / 255, blue: numbers[2] / 255)
                    .opacity(numbers[3])
            }
        }
        return nil
    }
}

/// Cuts sprite-sheet cells out of the fox's pictures (and remembers them).
final class PictureBox {
    private var sheets: [String: UIImage] = [:]
    private var cells: [String: Image] = [:]

    func add(_ name: String, data: Data) {
        if let image = UIImage(data: data) { sheets[name] = image }
    }

    var names: Set<String> { Set(sheets.keys) }

    func cell(_ name: String, frame: Int, columns: Int, rows: Int) -> Image? {
        let id = "\(name)#\(frame)/\(columns)x\(rows)"
        if let cached = cells[id] { return cached }
        guard let sheet = sheets[name], let cg = sheet.cgImage else { return nil }
        let w = CGFloat(cg.width) / CGFloat(columns), h = CGFloat(cg.height) / CGFloat(rows)
        let rect = CGRect(x: CGFloat(frame % columns) * w, y: CGFloat(frame / columns) * h, width: w, height: h)
        guard let piece = cg.cropping(to: rect.integral) else { return nil }
        let image = Image(decorative: piece, scale: 1)
        cells[id] = image
        return image
    }
}

/// Replays one frame's drawing commands on a SwiftUI Canvas.
enum FrameRenderer {
    static func draw(_ ops: [DrawOp], in context: GraphicsContext, scale: CGFloat, pictures: PictureBox) {
        var ctx = context
        ctx.scaleBy(x: scale, y: scale)
        var stack: [GraphicsContext] = []
        let round = StrokeStyle(lineWidth: 1, lineCap: .round, lineJoin: .round)
        for op in ops {
            switch op {
            case .save: stack.append(ctx)
            case .restore: if let last = stack.popLast() { ctx = last }
            case let .translate(x, y): ctx.translateBy(x: x, y: y)
            case let .rotate(degrees): ctx.rotate(by: .degrees(degrees))
            case let .scale(x, y): ctx.scaleBy(x: x, y: y)
            case let .clip(path): ctx.clip(to: path)
            case let .fillRect(rect, color): ctx.fill(Path(rect), with: .color(color))
            case let .shape(path, fill, stroke, width):
                if let fill { ctx.fill(path, with: .color(fill)) }
                if let stroke {
                    var style = round
                    style.lineWidth = width
                    ctx.stroke(path, with: .color(stroke), style: style)
                }
            case let .gradient(path, start, end, stops, stroke, width):
                ctx.fill(path, with: .linearGradient(Gradient(stops: stops), startPoint: start, endPoint: end))
                if let stroke {
                    var style = round
                    style.lineWidth = width
                    ctx.stroke(path, with: .color(stroke), style: style)
                }
            case let .text(text, at, size, color, bold):
                let label = Text(text).font(.system(size: size * 1.33, weight: bold ? .bold : .regular))
                    .foregroundColor(color)
                ctx.draw(label, at: at, anchor: .topLeading)
            case let .picture(name, frame, columns, rows, rect, opacity):
                guard let image = pictures.cell(name, frame: frame, columns: columns, rows: rows) else { continue }
                var faded = ctx
                faded.opacity = opacity
                faded.draw(image, in: rect)
            }
        }
    }
}
