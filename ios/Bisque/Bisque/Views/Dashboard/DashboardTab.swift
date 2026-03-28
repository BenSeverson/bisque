import SwiftUI

struct DashboardTab: View {
    @Environment(KilnConnection.self) private var connection
    @Environment(KilnStore.self) private var store
    @State private var viewModel = DashboardViewModel()

    private var selectedProfile: FiringProfile? {
        store.profiles.first(where: { $0.id == viewModel.selectedProfileId })
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    // Connection banner
                    if !connection.webSocket.isConnected && connection.connectionState.isConnected {
                        ErrorBanner(message: "Connection lost — reconnecting...")
                    }

                    // Status + Temperature
                    TemperatureCardView(
                        currentTemp: store.progress.currentTemp,
                        targetTemp: store.progress.targetTemp,
                        status: store.progress.firingStatus,
                        unit: store.settings.tempUnit
                    )

                    // Stats row
                    HStack(spacing: 12) {
                        StatCard(title: "Segment", value: "\(store.progress.currentSegment + 1)/\(store.progress.totalSegments)")
                        StatCard(title: "Elapsed", value: Formatters.formatDuration(seconds: store.progress.elapsedTime))
                        StatCard(title: "Remaining", value: Formatters.formatDuration(seconds: store.progress.estimatedTimeRemaining))
                    }
                    .padding(.horizontal)

                    // Firing controls
                    FiringControlsView(
                        viewModel: viewModel,
                        profiles: store.profiles,
                        progress: store.progress,
                        client: connection.apiClient,
                        store: store
                    )

                    // Segments
                    if let profile = selectedProfile {
                        SegmentListView(
                            segments: profile.segments,
                            currentSegment: store.progress.currentSegment,
                            isActive: store.progress.isActive
                        )
                    }

                    // Chart
                    FiringChartView(
                        temperatureHistory: store.temperatureHistory,
                        profilePath: viewModel.computeProfilePath(for: selectedProfile),
                        unit: store.settings.tempUnit
                    )
                }
                .padding(.vertical)
            }
            .navigationTitle("Dashboard")
            .onAppear {
                if viewModel.selectedProfileId == nil, let first = store.profiles.first {
                    viewModel.selectedProfileId = first.id
                }
                if let activeProfileId = store.progress.profileId, store.progress.isActive {
                    viewModel.selectedProfileId = activeProfileId
                }
            }
        }
    }
}

struct StatCard: View {
    let title: String
    let value: String

    var body: some View {
        VStack(spacing: 4) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.headline)
                .monospacedDigit()
        }
        .frame(maxWidth: .infinity)
        .padding(12)
        .background(Color(.systemGray6))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }
}

#Preview {
    DashboardTab()
        .environment(KilnConnection())
        .environment(KilnStore())
}
