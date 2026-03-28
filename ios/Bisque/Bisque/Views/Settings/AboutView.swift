import SwiftUI

struct AboutView: View {
    @Environment(KilnConnection.self) private var connection
    @Environment(KilnStore.self) private var store

    var body: some View {
        Form {
            if let info = store.systemInfo {
                Section("Device") {
                    LabeledContent("Model", value: info.model)
                    LabeledContent("Firmware", value: info.firmware)
                    LabeledContent("Uptime", value: Formatters.formatDurationLong(seconds: info.uptimeSeconds))
                }

                Section("Memory") {
                    LabeledContent("Free Heap", value: "\(info.freeHeap / 1024) KB")
                    LabeledContent("SPIFFS Used", value: "\(info.spiffsUsed / 1024) / \(info.spiffsTotal / 1024) KB")
                }

                Section("Status") {
                    LabeledContent("Board Temp", value: "\(String(format: "%.1f", info.boardTempC))°C")
                    LabeledContent("Element Hours", value: Formatters.formatDuration(seconds: info.elementHoursS))
                    LabeledContent("Emergency Stop", value: info.emergencyStop ? "Active" : "Off")
                    if info.lastErrorCode != 0 {
                        LabeledContent("Last Error", value: "\(info.lastErrorCode)")
                            .foregroundStyle(.red)
                    }
                }
            } else {
                ProgressView("Loading system info...")
            }
        }
        .navigationTitle("System Info")
        .task {
            if let client = connection.apiClient {
                await store.loadSystemInfo(using: client)
            }
        }
    }
}
