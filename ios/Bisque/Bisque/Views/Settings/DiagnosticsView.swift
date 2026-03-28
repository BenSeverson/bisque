import SwiftUI

struct DiagnosticsView: View {
    @Environment(KilnConnection.self) private var connection
    @Bindable var viewModel: SettingsViewModel

    var body: some View {
        Form {
            Section("Thermocouple") {
                Button("Read Thermocouple") {
                    guard let client = connection.apiClient else { return }
                    Task { await viewModel.readThermocouple(using: client) }
                }
                .disabled(viewModel.isReadingTC)

                if let tc = viewModel.tcDiag {
                    LabeledContent("Temperature", value: "\(String(format: "%.1f", tc.temperatureC))°C")
                    LabeledContent("Adjusted", value: "\(String(format: "%.1f", tc.temperatureAdjustedC))°C")
                    LabeledContent("Internal", value: "\(String(format: "%.1f", tc.internalTempC))°C")
                    LabeledContent("Offset", value: "\(String(format: "%.1f", tc.tcOffsetC))°C")
                    LabeledContent("Reading Age", value: "\(tc.readingAgeMs)ms")

                    if tc.fault {
                        Section("Faults") {
                            if tc.openCircuit {
                                Label("Open Circuit", systemImage: "exclamationmark.triangle")
                                    .foregroundStyle(.red)
                            }
                            if tc.shortGnd {
                                Label("Short to GND", systemImage: "exclamationmark.triangle")
                                    .foregroundStyle(.red)
                            }
                            if tc.shortVcc {
                                Label("Short to VCC", systemImage: "exclamationmark.triangle")
                                    .foregroundStyle(.red)
                            }
                        }
                    }
                }
            }

            Section("Relay") {
                Button("Test Relay (2 sec)") {
                    guard let client = connection.apiClient else { return }
                    Task { await viewModel.testRelay(using: client) }
                }
                .disabled(viewModel.isTestingRelay)

                if viewModel.isTestingRelay {
                    ProgressView("Testing relay...")
                }
            }
        }
        .navigationTitle("Diagnostics")
    }
}
