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
                        Text(statusLabel(context.state.status))
                            .font(.caption2)
                            .foregroundStyle(statusColor(context.state.status))
                    }
                }

                DynamicIslandExpandedRegion(.trailing) {
                    VStack(alignment: .trailing, spacing: 2) {
                        Text("\(Int(context.state.currentTemp))°")
                            .font(.title2.bold())
                            .foregroundStyle(statusColor(context.state.status))
                        Text("→ \(Int(context.state.targetTemp))°C")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }

                DynamicIslandExpandedRegion(.bottom) {
                    VStack(spacing: 4) {
                        ProgressView(value: context.state.progress)
                            .tint(statusColor(context.state.status))
                        HStack {
                            Text("Seg \(context.state.currentSegment + 1)/\(context.state.totalSegments)")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text(formatRemaining(context.state.estimatedSecondsRemaining))
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            } compactLeading: {
                HStack(spacing: 4) {
                    Text("🔥")
                    Text("\(Int(context.state.currentTemp))°")
                        .font(.caption.bold())
                        .foregroundStyle(statusColor(context.state.status))
                }
            } compactTrailing: {
                Text(formatRemaining(context.state.estimatedSecondsRemaining))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            } minimal: {
                Text("🔥")
            }
        }
    }

    private func statusColor(_ status: String) -> Color {
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

    private func statusLabel(_ status: String) -> String {
        status.capitalized
    }

    private func formatRemaining(_ seconds: Int) -> String {
        let h = seconds / 3600
        let m = (seconds % 3600) / 60
        if h > 0 { return "\(h)h \(m)m" }
        return "\(m)m"
    }
}
