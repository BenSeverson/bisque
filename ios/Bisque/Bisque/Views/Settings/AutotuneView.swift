import SwiftUI

struct AutotuneView: View {
    @Environment(KilnConnection.self) private var connection
    @Bindable var viewModel: SettingsViewModel

    var body: some View {
        Form {
            Section("Configuration") {
                HStack {
                    Text("Setpoint")
                    Spacer()
                    TextField("°C", value: $viewModel.autotuneSetpoint, format: .number)
                        .keyboardType(.decimalPad)
                        .multilineTextAlignment(.trailing)
                        .frame(width: 80)
                    Text("°C")
                }
            }

            Section("Controls") {
                HStack(spacing: 12) {
                    Button("Start") {
                        guard let client = connection.apiClient else { return }
                        Task { await viewModel.startAutotune(using: client) }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.orange)

                    Button("Stop") {
                        guard let client = connection.apiClient else { return }
                        Task { await viewModel.stopAutotune(using: client) }
                    }
                    .buttonStyle(.bordered)
                }
            }

            if let status = viewModel.autotuneStatus {
                Section("Status") {
                    LabeledContent("State", value: status.state.capitalized)
                    LabeledContent("Current Temp", value: "\(Int(status.currentTemp))°C")
                    LabeledContent("Elapsed", value: Formatters.formatDuration(seconds: status.elapsedTime))
                }

                Section("PID Gains") {
                    LabeledContent("Kp", value: String(format: "%.4f", status.currentGains.kp))
                    LabeledContent("Ki", value: String(format: "%.4f", status.currentGains.ki))
                    LabeledContent("Kd", value: String(format: "%.4f", status.currentGains.kd))
                }
            }
        }
        .navigationTitle("PID Auto-Tune")
    }
}
