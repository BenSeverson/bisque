import SwiftUI
import WidgetKit
import ActivityKit

struct FiringLockScreenView: View {
    let context: ActivityViewContext<FiringActivityAttributes>

    var body: some View {
        VStack(spacing: 8) {
            // Header
            HStack {
                HStack(spacing: 6) {
                    Text("🔥")
                    VStack(alignment: .leading, spacing: 1) {
                        Text(context.attributes.profileName)
                            .font(.subheadline.bold())
                            .lineLimit(1)
                        Text("\(statusLabel) — Segment \(context.state.currentSegment + 1)/\(context.state.totalSegments)")
                            .font(.caption2)
                            .foregroundStyle(statusColor)
                    }
                }

                Spacer()

                VStack(alignment: .trailing, spacing: 1) {
                    Text("\(Int(context.state.currentTemp))°")
                        .font(.title.bold())
                        .foregroundStyle(statusColor)
                    Text("→ \(Int(context.state.targetTemp))°C")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }

            // Progress
            ProgressView(value: context.state.progress)
                .tint(statusColor)

            // Footer
            HStack {
                Text(elapsedText)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Spacer()
                Text("~\(remainingText) remaining")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .activityBackgroundTint(.black)
    }

    private var statusColor: Color {
        switch context.state.status {
        case "heating":  return Color(red: 1.0, green: 0.65, blue: 0.0)
        case "holding":  return Color(red: 1.0, green: 1.0, blue: 0.0)
        case "cooling":  return Color(red: 0.29, green: 0.56, blue: 0.85)
        case "error":    return Color(red: 1.0, green: 0.23, blue: 0.19)
        case "complete": return Color(red: 0.19, green: 0.82, blue: 0.35)
        case "paused":   return Color(red: 1.0, green: 1.0, blue: 0.0)
        default:         return .secondary
        }
    }

    private var statusLabel: String {
        context.state.status.capitalized
    }

    private var elapsedText: String {
        let elapsed = Date().timeIntervalSince(context.attributes.startTime)
        let h = Int(elapsed) / 3600
        let m = (Int(elapsed) % 3600) / 60
        if h > 0 { return "\(h)h \(m)m elapsed" }
        return "\(m)m elapsed"
    }

    private var remainingText: String {
        let s = context.state.estimatedSecondsRemaining
        let h = s / 3600
        let m = (s % 3600) / 60
        if h > 0 { return "\(h)h \(m)m" }
        return "\(m)m"
    }
}
