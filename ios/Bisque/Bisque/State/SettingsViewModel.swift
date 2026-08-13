import SwiftUI
import Combine

@MainActor @Observable
final class SettingsViewModel {
    var isSaving = false
    var error: String?

    // Autotune
    var autotuneSetpoint: Double = 500
    var autotuneStatus: AutotuneStatus?
    var isAutotunePolling = false

    // OTA — manual upload
    var otaProgress: Double = 0
    var isUploading = false
    var otaMessage: String?

    // OTA — GitHub update check / install
    var availableUpdate: OtaCheckResponse?
    var isCheckingUpdate = false
    var isInstalling = false
    var installProgress: Double?

    // OTA — partitions, confirm and rollback (#177)
    var otaStatus: OtaStatus?
    /// Set when a status fetch failed — a controller too old to serve the
    /// endpoint 404s it. Deliberately not routed through `error`, which drives
    /// the red banner: being unable to *describe* the partitions is not a
    /// failure of anything the user asked for, and it would otherwise paint the
    /// screen red every time the OTA view opened against an older kiln.
    var otaStatusUnavailable = false
    var isLoadingOtaStatus = false
    var isConfirmingFirmware = false
    var isRollingBack = false
    /// Bumped by every `loadOtaStatus()`; only the newest may write the result.
    @ObservationIgnored private var otaLoadGeneration = 0

    @ObservationIgnored private var otaCancellable: AnyCancellable?

    // Diagnostics
    var tcDiag: DiagThermocouple?
    var isTestingRelay = false
    var isReadingTC = false

    func saveSettings(_ settings: KilnSettings, using client: KilnAPIClient, store: KilnStore) async {
        isSaving = true
        error = nil
        do {
            _ = try await client.saveSettings(settings)
            store.settings = settings
            isSaving = false
        } catch {
            self.error = error.localizedDescription
            isSaving = false
        }
    }

    // MARK: - Autotune

    func startAutotune(using client: KilnAPIClient) async {
        error = nil
        do {
            _ = try await client.startAutotune(setpoint: autotuneSetpoint)
            isAutotunePolling = true
            await pollAutotuneStatus(using: client)
        } catch {
            self.error = error.localizedDescription
        }
    }

    func stopAutotune(using client: KilnAPIClient) async {
        error = nil
        isAutotunePolling = false
        do {
            _ = try await client.stopAutotune()
            autotuneStatus = try await client.getAutotuneStatus()
        } catch {
            self.error = error.localizedDescription
        }
    }

    func pollAutotuneStatus(using client: KilnAPIClient) async {
        while isAutotunePolling {
            do {
                autotuneStatus = try await client.getAutotuneStatus()
                // `complete` and `failed` are terminal too. The firmware used
                // to flatten every ending onto `idle`; now that it reports them
                // distinctly (#216), a loop that only stops on the old two
                // would poll a finished tune every two seconds forever — and
                // starting another would stack a second loop on top.
                if let state = autotuneStatus?.state,
                   ["idle", "stopped", "complete", "failed"].contains(state) {
                    isAutotunePolling = false
                    return
                }
            } catch {
                self.error = error.localizedDescription
                isAutotunePolling = false
                return
            }
            try? await Task.sleep(for: .seconds(2))
        }
    }

    // MARK: - OTA

    /// Takes the firmware bytes, not a file URL: the caller reads them while the
    /// picked file's security scope is still open, which this task could not do
    /// (#141).
    func uploadFirmware(_ firmware: Data, using client: KilnAPIClient) async {
        isUploading = true
        otaProgress = 0
        otaMessage = nil
        error = nil

        do {
            _ = try await client.uploadOTA(firmware: firmware) { [weak self] progress in
                Task { @MainActor in
                    self?.otaProgress = progress
                }
            }
            otaMessage = "Update complete. Kiln is rebooting..."
            markOtaStatusStale()
            isUploading = false
        } catch {
            self.error = error.localizedDescription
            isUploading = false
        }
    }

    // MARK: - OTA (GitHub update)

    func checkForUpdate(using client: KilnAPIClient) async {
        isCheckingUpdate = true
        error = nil
        otaMessage = nil
        do {
            let result = try await client.checkOTA()
            availableUpdate = result
            if !result.updateAvailable {
                otaMessage = "You're on the latest version (\(result.current))."
            }
        } catch {
            self.error = error.localizedDescription
        }
        isCheckingUpdate = false
    }

    func installUpdate(using client: KilnAPIClient, ws: KilnWebSocketManager) async {
        isInstalling = true
        installProgress = 0
        error = nil
        otaMessage = nil

        otaCancellable = ws.otaSubject
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                guard let self else { return }
                switch event {
                case .progress(let pct):
                    self.installProgress = pct
                case .complete:
                    self.installProgress = 100
                    self.otaMessage = "Update installed. Kiln is rebooting..."
                    // The partitions on screen belong to the image just
                    // replaced; the new one may be pending verification.
                    self.markOtaStatusStale()
                    // Without this the flag stays true after a successful
                    // install, leaving Check for Updates / Install disabled
                    // until the view is recreated (#145). Matches the .failed
                    // branch; the subscription itself is replaced (and so
                    // cancelled) by the next installUpdate().
                    self.isInstalling = false
                    // Drop the offer we just installed. Re-enabling the buttons
                    // while `availableUpdate.updateAvailable` is still true
                    // leaves OTAUpdateView showing "Install" for the version
                    // now running, and tapping it once the kiln is back only
                    // earns the firmware's "Already on the latest version".
                    // Clearing it restores "Check for Updates", which is the
                    // honest next action.
                    self.availableUpdate = nil
                case .failed(let message):
                    self.error = message
                    self.isInstalling = false
                    self.installProgress = nil
                }
            }

        do {
            _ = try await client.installOTA()
        } catch {
            self.error = error.localizedDescription
            isInstalling = false
            installProgress = nil
            otaCancellable = nil
        }
    }

    // MARK: - OTA (partitions and rollback)

    /// Drop the partition state after an update or a rollback.
    ///
    /// The slot, version and image state on screen describe the firmware that
    /// was just replaced, and the kiln is rebooting, so a refetch would fail
    /// anyway. Marking it unreadable rather than leaving the old values up is
    /// the honest state, and the Refresh button in the section is how the user
    /// picks it back up once the kiln answers again — otherwise a new image
    /// could sit in pending-verify for its whole confirmation window with the
    /// Confirm button never shown (#177).
    func markOtaStatusStale() {
        otaStatus = nil
        otaStatusUnavailable = true
    }

    /// Reads the partition state, discarding the answer if a newer read started
    /// while it was in flight.
    ///
    /// Three things call this — the view's `.task`, the Refresh button, and the
    /// reload after a confirm — and around a reboot they overlap by design: the
    /// user taps Refresh, gets nothing, and taps again. Without the generation
    /// check, a slow pre-reboot request completing after a fast post-reboot one
    /// would restore the outgoing image's slot and `rollbackAvailable` on top of
    /// the new state, or a late failure would erase state that had just loaded.
    /// Everything here is `@MainActor`, so the counter needs no locking.
    func loadOtaStatus(using client: KilnAPIClient) async {
        otaLoadGeneration &+= 1
        let generation = otaLoadGeneration
        isLoadingOtaStatus = true
        defer {
            if generation == otaLoadGeneration {
                isLoadingOtaStatus = false
            }
        }

        do {
            let status = try await client.getOTAStatus()
            guard generation == otaLoadGeneration else { return }
            otaStatus = status
            otaStatusUnavailable = false
        } catch {
            guard generation == otaLoadGeneration else { return }
            otaStatus = nil
            otaStatusUnavailable = true
        }
    }

    func confirmFirmware(using client: KilnAPIClient) async {
        isConfirmingFirmware = true
        error = nil
        do {
            // The firmware's own wording: it distinguishes a confirmation from
            // a no-op on an image that was already valid, and which of the two
            // happened is the whole answer to the question the tap asked.
            otaMessage = try await client.confirmOTA().message
            // pendingVerify is what put the button on screen, so the state it
            // was read from is stale the moment this succeeds.
            await loadOtaStatus(using: client)
        } catch {
            self.error = error.localizedDescription
        }
        isConfirmingFirmware = false
    }

    func rollbackFirmware(using client: KilnAPIClient) async {
        isRollingBack = true
        error = nil
        otaMessage = nil
        do {
            switch try await client.rollbackOTA() {
            case .acknowledged:
                otaMessage = "Rolling back. Kiln is rebooting..."
            case .unacknowledged:
                /* The request went out and nothing came back, which is what the
                   reboot looks like from here — but it is not proof, so this
                   says what is known and names the check that settles it. */
                otaMessage = """
                    Rollback sent, but the kiln stopped answering before it replied. \
                    That is expected while it reboots — reopen this screen shortly and \
                    check the running version.
                    """
            }
            // The partitions on screen describe the image on its way out.
            markOtaStatusStale()
            // The offer to install whatever was newest belongs to the firmware
            // being left behind; the version list is worth rechecking after the
            // reboot rather than acting on now.
            availableUpdate = nil
        } catch {
            // 400 with nothing to roll back to, 409 during a firing. Both mean
            // the firmware did not change.
            self.error = error.localizedDescription
        }
        isRollingBack = false
    }

    // MARK: - Diagnostics

    func testRelay(using client: KilnAPIClient) async {
        isTestingRelay = true
        error = nil
        do {
            _ = try await client.testRelay(durationSeconds: 2)
            isTestingRelay = false
        } catch {
            self.error = error.localizedDescription
            isTestingRelay = false
        }
    }

    func readThermocouple(using client: KilnAPIClient) async {
        isReadingTC = true
        error = nil
        do {
            tcDiag = try await client.getThermocoupleDiag()
            isReadingTC = false
        } catch {
            self.error = error.localizedDescription
            isReadingTC = false
        }
    }
}
