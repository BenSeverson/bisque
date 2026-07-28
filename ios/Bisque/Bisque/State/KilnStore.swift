import SwiftUI
import Combine

@MainActor @Observable
final class KilnStore {
    var progress: FiringProgress = .idle
    var profiles: [FiringProfile] = []
    var settings: KilnSettings = .default
    var history: [HistoryRecord] = []
    var systemInfo: SystemInfo?
    var temperatureHistory: [TemperatureDataPoint] = []
    var isLoading = false
    var error: String?

    private var cancellables = Set<AnyCancellable>()
    private var previousStatus: String = "idle"

    /// Highest temperature seen across the current firing.
    ///
    /// The completion notification used to report `progress.currentTemp` at the
    /// moment status flipped to "complete", but the firmware flips only once
    /// cooling has begun — so a cone 6 firing peaking near 1230°C reported
    /// something like 1100°C as its "peak" (#146). Tracked here because no
    /// status frame carries a peak field.
    private(set) var peakTempC: Double = 0

    private static let maxHistoryPoints = 200

    var notificationManager: NotificationManager?
    var activityManager: FiringActivityManager?

    func subscribe(to webSocket: KilnWebSocketManager) {
        webSocket.updateSubject
            .receive(on: DispatchQueue.main)
            .sink { [weak self] update in
                self?.handleWebSocketUpdate(update)
            }
            .store(in: &cancellables)
    }

    func refreshAll(using client: KilnAPIClient) async {
        isLoading = true
        error = nil

        do {
            async let statusTask = client.getStatus()
            async let profilesTask = client.getProfiles()
            async let settingsTask = client.getSettings()

            let (status, profiles, settings) = try await (statusTask, profilesTask, settingsTask)

            self.progress = FiringProgress(
                isActive: status.isActive,
                profileId: status.profileId,
                startTime: nil,
                currentTemp: status.currentTemp,
                targetTemp: status.targetTemp,
                currentSegment: status.currentSegment,
                totalSegments: status.totalSegments,
                elapsedTime: status.elapsedTime,
                estimatedTimeRemaining: status.estimatedTimeRemaining,
                status: status.status
            )
            self.previousStatus = status.status
            self.profiles = profiles
            self.settings = settings
            self.isLoading = false
        } catch {
            self.error = error.localizedDescription
            self.isLoading = false
        }
    }

    func loadHistory(using client: KilnAPIClient) async {
        do {
            history = try await client.getHistory()
        } catch {
            self.error = error.localizedDescription
        }
    }

    func loadSystemInfo(using client: KilnAPIClient) async {
        do {
            systemInfo = try await client.getSystemInfo()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func handleWebSocketUpdate(_ update: TempUpdateData) {
        progress = FiringProgress(
            isActive: update.isActive,
            profileId: progress.profileId,
            startTime: progress.startTime,
            currentTemp: update.currentTemp,
            targetTemp: update.targetTemp,
            currentSegment: update.currentSegment,
            totalSegments: update.totalSegments,
            elapsedTime: update.elapsedTime,
            estimatedTimeRemaining: update.estimatedTimeRemaining,
            status: update.status
        )

        // Track the firing's high-water mark while it is still running; once the
        // status reaches "complete" the kiln is already cooling.
        if update.isActive {
            peakTempC = max(peakTempC, update.currentTemp)
        }

        // Append to temperature history for chart (max 200 points)
        let timeMin = update.elapsedTime / 60.0
        temperatureHistory.append(TemperatureDataPoint(
            time: timeMin,
            temp: update.currentTemp,
            target: update.targetTemp
        ))
        // Trim in one shot. removeFirst() shifts the whole array on every
        // message; harmless at 200 elements but needlessly O(n) per frame (#155).
        if temperatureHistory.count > Self.maxHistoryPoints {
            temperatureHistory.removeFirst(temperatureHistory.count - Self.maxHistoryPoints)
        }

        // Detect status transitions for notifications and Live Activity
        let newStatus = update.status
        if newStatus != previousStatus {
            handleStatusTransition(from: previousStatus, to: newStatus)
            previousStatus = newStatus
        }

        // Update Live Activity
        if update.isActive {
            activityManager?.update(
                temp: update.currentTemp,
                target: update.targetTemp,
                status: update.status,
                segment: update.currentSegment,
                totalSegments: update.totalSegments,
                remaining: Int(update.estimatedTimeRemaining),
                elapsed: update.elapsedTime,
                estimatedTotal: update.elapsedTime + update.estimatedTimeRemaining
            )
        }
    }

    private func handleStatusTransition(from oldStatus: String, to newStatus: String) {
        switch newStatus {
        case "complete":
            notificationManager?.sendFiringComplete(
                profileName: profileName(for: progress.profileId),
                peakTempC: peakTempC,
                unit: settings.tempUnit
            )
            activityManager?.end(status: newStatus)
            peakTempC = 0
        case "error":
            notificationManager?.sendFiringError(
                profileName: profileName(for: progress.profileId)
            )
            activityManager?.end(status: newStatus)
            // Reset on *every* way a firing can end, not just "complete".
            // A stopped or errored firing used to leave its high-water mark in
            // place, so the next — possibly much cooler — firing reported the
            // earlier peak in its completion notification, which is the same
            // class of lie #146 was about.
            peakTempC = 0
        case "idle" where oldStatus != "idle":
            activityManager?.end(status: newStatus)
            peakTempC = 0
        default:
            break
        }
    }

    func startLiveActivity(profileName: String) {
        activityManager?.start(profileName: profileName)
    }

    func clearTemperatureHistory() {
        temperatureHistory = []
    }

    private func profileName(for id: String?) -> String {
        guard let id = id else { return "Unknown" }
        return profiles.first(where: { $0.id == id })?.name ?? "Unknown"
    }
}
