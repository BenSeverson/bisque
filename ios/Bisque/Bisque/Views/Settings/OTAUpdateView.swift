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
                /* Read the bytes here, inside the scope, rather than handing the
                   URL to the upload task (#141). `defer` fires when this closure
                   returns — which is before a detached Task would have got as
                   far as opening the file — so the read used to happen after
                   access had been revoked. Anything outside the app sandbox
                   (iCloud Drive, Files) failed with a permission error, which
                   is to say manual OTA upload was broken for the normal case. */
                guard url.startAccessingSecurityScopedResource() else {
                    viewModel.error = "Could not get permission to read that file."
                    return
                }
                defer { url.stopAccessingSecurityScopedResource() }

                guard let client = connection.apiClient else { return }
                let firmware: Data
                do {
                    firmware = try Data(contentsOf: url)
                } catch {
                    viewModel.error = "Could not read \(url.lastPathComponent): \(error.localizedDescription)"
                    return
                }
                Task { await viewModel.uploadFirmware(firmware, using: client) }
            case .failure:
                break
            }
        }
    }
}
