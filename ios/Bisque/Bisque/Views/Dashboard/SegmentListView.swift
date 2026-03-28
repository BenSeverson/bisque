import SwiftUI

struct SegmentListView: View {
    let segments: [FiringSegment]
    let currentSegment: Int
    let isActive: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Segments")
                .font(.headline)
                .padding(.horizontal)

            ForEach(Array(segments.enumerated()), id: \.element.id) { index, segment in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(segment.name)
                            .font(.subheadline.weight(.medium))
                        Text("\(segment.rampRate > 0 ? "+" : "")\(Int(segment.rampRate))°C/hr → \(Int(segment.targetTemp))°C\(segment.holdTime > 0 ? ", hold \(Int(segment.holdTime))m" : "")")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if index == currentSegment && isActive {
                        StatusBadge(status: .heating)
                    }
                }
                .padding(10)
                .background(index == currentSegment && isActive ? Color.orange.opacity(0.1) : Color(.systemGray5))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
        .padding()
        .background(Color(.systemGray6))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .padding(.horizontal)
    }
}
