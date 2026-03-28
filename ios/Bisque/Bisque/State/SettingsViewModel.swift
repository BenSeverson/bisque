import SwiftUI

@MainActor @Observable
final class SettingsViewModel {
    var isSaving = false
    var error: String?

    // Autotune
    var autotuneSetpoint: Double = 500
    var autotuneStatus: AutotuneStatus?
    var isAutotunePolling = false

    // OTA
    var otaProgress: Double = 0
    var isUploading = false
    var otaMessage: String?

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
