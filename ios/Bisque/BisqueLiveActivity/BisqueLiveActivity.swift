import ActivityKit
import WidgetKit
import SwiftUI

struct BisqueLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: FiringActivityAttributes.self) { context in
            // Lock screen view
            FiringLockScreenView(context: context)
        } dynamicIsland: { context in
            DynamicIsland {
                // Expanded
                DynamicIslandExpandedRegion(.leading) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("🔥 \(context.attributes.profileName)")
                            .font(.caption.bold())
                            .lineLimit(1)
                        Text(context.state.status.capitalized)
                            .font(.caption2)
                            .foregroundStyle(liveActivityStatusColor(context.state.status))
                    }
                }

                DynamicIslandExpandedRegion(.trailing) {
                    VStack(alignment: .trailing, spacing: 2) {
                        Text("\(Int(context.state.currentTemp))°")
                            .font(.title2.bold())
                            .foregroundStyle(liveActivityStatusColor(context.state.status))
                        Text("→ \(Int(context.state.targetTemp))°C")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    // Dimmed rather than hidden: the layout should not jump, and
                    // a faded number reads as "last known" (#147).
                    .opacity(context.isStale ? 0.4 : 1)
                }

                DynamicIslandExpandedRegion(.bottom) {
                    VStack(spacing: 4) {
                        ProgressView(value: context.state.progress)
                            .tint(liveActivityStatusColor(context.state.status))
                        HStack {
                            Text("Seg \(context.state.currentSegment + 1)/\(context.state.totalSegments)")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            Spacer()
                            if context.isStale {
                                Text("not updating")
                                    .font(.caption2)
                                    .foregroundStyle(.orange)
                            } else {
                                Text(liveActivityFormatDuration(context.state.estimatedSecondsRemaining))
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            } compactLeading: {
                HStack(spacing: 4) {
                    Text("🔥")
                    Text("\(Int(context.state.currentTemp))°")
                        .font(.caption.bold())
                        .foregroundStyle(liveActivityStatusColor(context.state.status))
                }
                .opacity(context.isStale ? 0.4 : 1)
            } compactTrailing: {
                // There is no room for an explanation here, so the countdown —
                // the most obviously wrong thing to keep showing from a frozen
                // frame — is replaced by a warning glyph.
                if context.isStale {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                } else {
                    Text(liveActivityFormatDuration(context.state.estimatedSecondsRemaining))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            } minimal: {
                Text("🔥")
                    .opacity(context.isStale ? 0.4 : 1)
            }
        }
    }

}

// Shared helpers for the Live Activity target
func liveActivityStatusColor(_ status: String) -> Color {
    switch status {
    case "heating":  return Color(red: 1.0, green: 0.65, blue: 0.0)
    case "holding":  return Color(red: 1.0, green: 1.0, blue: 0.0)
    case "cooling":  return Color(red: 0.29, green: 0.56, blue: 0.85)
    case "error":    return Color(red: 1.0, green: 0.23, blue: 0.19)
    case "complete": return Color(red: 0.19, green: 0.82, blue: 0.35)
    case "paused":   return Color(red: 1.0, green: 1.0, blue: 0.0)
    default:         return .secondary
    }
}

func liveActivityFormatDuration(_ seconds: Int) -> String {
    let h = seconds / 3600
    let m = (seconds % 3600) / 60
    if h > 0 { return "\(h)h \(m)m" }
    return "\(m)m"
}
