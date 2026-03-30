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
        liveActivityStatusColor(context.state.status)
    }

    private var statusLabel: String {
        context.state.status.capitalized
    }

    private var elapsedText: String {
        let elapsed = Int(Date().timeIntervalSince(context.attributes.startTime))
        return "\(liveActivityFormatDuration(elapsed)) elapsed"
    }

    private var remainingText: String {
        liveActivityFormatDuration(context.state.estimatedSecondsRemaining)
    }
}
