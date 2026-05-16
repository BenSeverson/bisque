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
                if autotuneStatus?.state == "idle" || autotuneStatus?.state == "stopped" {
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

    func uploadFirmware(fileURL: URL, using client: KilnAPIClient) async {
        isUploading = true
        otaProgress = 0
        otaMessage = nil
        error = nil

        do {
            _ = try await client.uploadOTA(fileURL: fileURL) { [weak self] progress in
                Task { @MainActor in
                    self?.otaProgress = progress
                }
            }
            otaMessage = "Update complete. Kiln is rebooting..."
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
