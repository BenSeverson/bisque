import SwiftUI

struct OTAUpdateView: View {
    @Environment(KilnConnection.self) private var connection
    @Environment(KilnStore.self) private var store
    @Bindable var viewModel: SettingsViewModel
    @State private var showFilePicker = false
    @State private var showRollbackConfirmation = false

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
                    .disabled(viewModel.isInstalling || viewModel.awaitingReboot)
                } else {
                    Button("Check for Updates") {
                        guard let client = connection.apiClient else { return }
                        Task { await viewModel.checkForUpdate(using: client) }
                    }
                    .disabled(
                        viewModel.isCheckingUpdate || viewModel.isInstalling
                            || viewModel.awaitingReboot)
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
                // Also while the kiln is restarting after an update or a
                // rollback: sending it another image then earns a 409 or a
                // dropped connection.
                .disabled(viewModel.isUploading || viewModel.awaitingReboot)
            }

            if viewModel.isUploading {
                Section("Upload Progress") {
                    ProgressView(value: viewModel.otaProgress, total: 100)
                    Text("\(Int(viewModel.otaProgress))%")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            /* The recovery half of the OTA story (#177). Every update is
               written to the inactive slot, so the image it replaced is still
               on the device — without this the only way back from a bad update
               was a USB cable and physical access to the kiln. */
            Section("Firmware Partitions") {
                if let status = viewModel.otaStatus {
                    if let running = status.running {
                        LabeledContent("Running Slot", value: running.label)
                        if let version = running.version {
                            LabeledContent("Running Version", value: version)
                        }
                    }
                    // Differs from the running slot only between a rollback
                    // request and the reboot that carries it out, which is
                    // exactly when it is worth reading.
                    if let boot = status.bootPartition {
                        LabeledContent("Boots Next From", value: boot)
                    }
                    if status.pendingVerify == true {
                        LabeledContent("Image State", value: "Pending verification")
                        Text("""
                            This image has not been marked valid yet. Until it is, the kiln \
                            reverts to the previous firmware if it reboots.
                            """)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Button("Confirm This Firmware") {
                            guard let client = connection.apiClient else { return }
                            Task { await viewModel.confirmFirmware(using: client) }
                        }
                        .disabled(viewModel.isConfirmingFirmware)
                    } else if let state = status.running?.state {
                        LabeledContent("Image State", value: state)
                    }

                    if status.rollbackAvailable {
                        Button("Roll Back to Previous Firmware", role: .destructive) {
                            showRollbackConfirmation = true
                        }
                        // handle_ota_rollback() answers 409 during a firing,
                        // and rebooting mid-firing would abandon the load.
                        .disabled(viewModel.isRollingBack || store.progress.isActive
                                  || viewModel.isInstalling || viewModel.isUploading
                                  || viewModel.awaitingReboot)
                    } else {
                        Text("""
                            No previous firmware to roll back to — the other slot is empty or was \
                            never booted successfully.
                            """)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                } else if viewModel.otaStatusUnavailable {
                    /* Either the kiln is rebooting after an update, or it is
                       too old to serve /ota/status and 404s it. Saying so beats
                       an empty section, which would read as "no previous
                       firmware" — a different claim entirely. */
                    Text("Could not read the partition state. The kiln may be restarting after an update.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    ProgressView()
                }

                /* `.task` runs once, when the screen appears. Installing from
                   this very screen therefore left the pre-update partitions on
                   display — or, after the reload above, nothing — until the
                   user navigated away and back. This is how they pick it up
                   again once the kiln has finished rebooting. */
                Button(viewModel.isLoadingOtaStatus ? "Reading..." : "Refresh Partition State") {
                    guard let client = connection.apiClient else { return }
                    Task { await viewModel.loadOtaStatus(using: client) }
                }
                .disabled(viewModel.isRollingBack || viewModel.isLoadingOtaStatus)
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
        .task {
            // No client means no connection at all; the placeholder spinner
            // would otherwise turn forever waiting on a request never made.
            guard let client = connection.apiClient else {
                viewModel.otaStatusUnavailable = true
                return
            }
            await viewModel.loadOtaStatus(using: client)
        }
        .confirmationDialog(
            "Roll back to the previous firmware?",
            isPresented: $showRollbackConfirmation,
            titleVisibility: .visible
        ) {
            Button("Roll Back", role: .destructive) {
                guard let client = connection.apiClient else { return }
                Task { await viewModel.rollbackFirmware(using: client) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("""
                The kiln reboots immediately into the firmware it ran before \
                \(viewModel.otaStatus?.running?.version ?? "the last update"). Settings, profiles \
                and history are kept. To come back to this version afterwards, install it again \
                from Check for Updates.
                """)
        }
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
