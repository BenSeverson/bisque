import SwiftUI

struct TemperatureCardView: View {
    let currentTemp: Double
    let targetTemp: Double
    let status: FiringStatus
    let unit: String

    var body: some View {
        VStack(spacing: 8) {
            StatusBadge(status: status)

            Text(Formatters.formatTemp(currentTemp, unit: unit))
                .font(.system(size: 72, weight: .ultraLight, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(status.color)

            HStack {
                Image(systemName: "arrow.right")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(Formatters.formatTemp(targetTemp, unit: unit))
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 24)
        .background(Color(.systemGray6))
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .padding(.horizontal)
    }
}

#Preview {
    TemperatureCardView(currentTemp: 1047, targetTemp: 1060, status: .heating, unit: "C")
}
