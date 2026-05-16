import SwiftUI

struct OTAUpdateView: View {
    @Environment(KilnConnection.self) private var connection
    @Bindable var viewModel: SettingsViewModel
    @State private var showFilePicker = false

    var body: some View {
        Form {
            Section("Check for Updates") {
                if let update = viewModel.availableUpdate, update.updateAvailable {
                    LabeledContent("Current", value: update.current)
                    LabeledContent("Available", value: update.latest)
                    Button("Install \(update.latest)") {
                        guard let client = connection.apiClient else { return }
                        Task { await viewModel.installUpdate(using: client, ws: connection.webSocket) }
                    }
                    .disabled(viewModel.isInstalling)
                } else {
                    Button("Check for Updates") {
                        guard let client = connection.apiClient else { return }
                        Task { await viewModel.checkForUpdate(using: client) }
                    }
                    .disabled(viewModel.isCheckingUpdate || viewModel.isInstalling)
                }
                Text("Updates are blocked while a firing is active.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if let pct = viewModel.installProgress {
                Section("Install Progress") {
                    ProgressView(value: pct, total: 100)
                    Text("\(Int(pct))%")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Section("Manual Firmware Update") {
                Button("Select Firmware File (.bin)") {
                    showFilePicker = true
                }
                .disabled(viewModel.isUploading)
            }

            if viewModel.isUploading {
                Section("Upload Progress") {
                    ProgressView(value: viewModel.otaProgress, total: 100)
                    Text("\(Int(viewModel.otaProgress))%")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if let message = viewModel.otaMessage {
                Section {
                    Label(message, systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                }
            }

            if let error = viewModel.error {
                Section {
                    Text(error).foregroundStyle(.red)
                }
            }
        }
        .navigationTitle("OTA Update")
        .fileImporter(isPresented: $showFilePicker, allowedContentTypes: [.data]) { result in
            switch result {
            case .success(let url):
                guard url.startAccessingSecurityScopedResource() else { return }
                defer { url.stopAccessingSecurityScopedResource() }
                guard let client = connection.apiClient else { return }
                Task { await viewModel.uploadFirmware(fileURL: url, using: client) }
            case .failure:
                break
            }
        }
    }
}
