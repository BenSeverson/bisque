import SwiftUI

struct StatusBadge: View {
    let status: FiringStatus

    var body: some View {
        Text(status.label)
            .font(.caption.bold())
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(status.color.opacity(0.2))
            .foregroundStyle(status.color)
            .clipShape(Capsule())
    }
}

#Preview {
    VStack(spacing: 8) {
        ForEach(FiringStatus.allCases, id: \.self) { status in
            StatusBadge(status: status)
        }
    }
}
