import SwiftUI
import UIKit
import WidgetKit

/// A home-screen and lock-screen widget: Kurama curled up asleep.
/// Tapping it opens the app and starts listening.
struct KuramaEntry: TimelineEntry {
    let date: Date
}

struct KuramaProvider: TimelineProvider {
    func placeholder(in context: Context) -> KuramaEntry { KuramaEntry(date: .now) }

    func getSnapshot(in context: Context, completion: @escaping (KuramaEntry) -> Void) {
        completion(KuramaEntry(date: .now))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<KuramaEntry>) -> Void) {
        completion(Timeline(entries: [KuramaEntry(date: .now)], policy: .never))
    }
}

struct KuramaWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: KuramaEntry

    private var fox: Image {
        Image(uiImage: UIImage(named: "red-white-fox-sleeping") ?? UIImage())
    }

    var body: some View {
        Group {
            switch family {
            case .accessoryCircular, .accessoryRectangular, .accessoryInline:
                // lock screen: a simple tinted fox
                fox.resizable().scaledToFit().widgetAccentable()
            default:
                VStack(spacing: 4) {
                    fox.resizable().scaledToFit()
                    Text("Tap to talk")
                        .font(.caption2.weight(.semibold))
                        .foregroundColor(Color(red: 0.36, green: 0.42, blue: 0.46))
                }
                .padding(6)
            }
        }
        .widgetURL(URL(string: "kurama://talk"))
        .containerBackground(for: .widget) {
            LinearGradient(colors: [Color(red: 0.75, green: 0.89, blue: 0.95),
                                    Color(red: 0.81, green: 0.90, blue: 0.75)],
                           startPoint: .top, endPoint: .bottom)
        }
    }
}

@main
struct KuramaWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "KuramaWidget", provider: KuramaProvider()) { entry in
            KuramaWidgetView(entry: entry)
        }
        .configurationDisplayName("Kurama")
        .description("Kurama sleeping on your home screen. Tap to talk.")
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryCircular, .accessoryRectangular])
    }
}
