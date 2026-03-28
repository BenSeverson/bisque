import SwiftUI

struct HistoryRecordRow: View {
    let record: HistoryRecord
    let unit: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(record.profileName)
                    .font(.headline)
                Spacer()
                OutcomeBadge(outcome: record.outcome)
            }
            HStack(spacing: 12) {
                Label(Formatters.formatDate(record.startTime), systemImage: "calendar")
                Label(Formatters.formatTemp(record.peakTemp, unit: unit), systemImage: "thermometer.high")
                Label(Formatters.formatDuration(seconds: record.durationS), systemImage: "clock")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
    }
}

struct OutcomeBadge: View {
    let outcome: String

    var color: Color {
        switch outcome {
        case "complete": return .green
        case "error": return .red
        case "aborted": return .yellow
        default: return .secondary
        }
    }

    var body: some View {
        Text(outcome.capitalized)
            .font(.caption.bold())
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .background(color.opacity(0.2))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }
}
