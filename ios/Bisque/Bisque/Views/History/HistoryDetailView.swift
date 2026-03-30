import SwiftUI
import Charts

struct HistoryDetailView: View {
    @Environment(KilnConnection.self) private var connection
    @Environment(KilnStore.self) private var store

    let record: HistoryRecord
    @Bindable var viewModel: HistoryViewModel

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                // Stats
                HStack(spacing: 20) {
                    VStack {
                        Text(Formatters.formatTemp(record.peakTemp, unit: store.settings.tempUnit))
                            .font(.title2.bold())
                        Text("Peak Temp").font(.caption).foregroundStyle(.secondary)
                    }
                    VStack {
                        Text(Formatters.formatDuration(seconds: record.durationS))
                            .font(.title2.bold())
                        Text("Duration").font(.caption).foregroundStyle(.secondary)
                    }
                    VStack {
                        OutcomeBadge(outcome: record.outcome)
                        Text("Outcome").font(.caption).foregroundStyle(.secondary)
                    }
                }
                .padding()

                // Trace chart
                if viewModel.isLoadingTrace {
                    ProgressView("Loading trace...")
                        .frame(height: 250)
                } else if !viewModel.traceData.isEmpty {
                    Chart {
                        ForEach(viewModel.traceData) { point in
                            LineMark(
                                x: .value("Time", point.time),
                                y: .value("Temp", store.settings.tempUnit == "F" ? TemperatureConverter.cToF(point.temp) : point.temp)
                            )
                            .foregroundStyle(.orange)
                        }
                    }
                    .chartXAxisLabel("Time (min)")
                    .chartYAxisLabel("Temperature (°\(store.settings.tempUnit))")
                    .frame(height: 250)
                    .padding(.horizontal)
                }

            }
            .padding(.vertical)
        }
        .navigationTitle(record.profileName)
        .task {
            if let client = connection.apiClient {
                await viewModel.loadTrace(for: record, using: client)
            }
        }
    }
}
