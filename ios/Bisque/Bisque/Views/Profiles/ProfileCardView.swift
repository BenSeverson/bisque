import SwiftUI

struct ProfileCardView: View {
    let profile: FiringProfile

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(profile.name)
                .font(.headline)
            Text(profile.description)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            HStack(spacing: 12) {
                Label("\(Int(profile.maxTemp))°C", systemImage: "thermometer.high")
                Label(Formatters.formatDuration(seconds: profile.estimatedDuration * 60), systemImage: "clock")
                Label("\(profile.segments.count) seg", systemImage: "list.number")
            }
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }
}

#Preview {
    ProfileCardView(profile: PreviewData.profile)
}
