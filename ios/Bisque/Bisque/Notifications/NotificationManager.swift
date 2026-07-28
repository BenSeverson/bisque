import UserNotifications
import UIKit

@MainActor
final class NotificationManager {
    init() {
        Task { @MainActor in
            await requestPermission()
        }
    }

    @discardableResult
    func requestPermission() async -> Bool {
        do {
            return try await UNUserNotificationCenter.current().requestAuthorization(
                options: [.alert, .sound, .badge]
            )
        } catch {
            return false
        }
    }

    /// Whether notifications may be posted *right now*.
    ///
    /// This used to be a Bool cached from `init`, so a user who granted
    /// permission later in iOS Settings stayed silently opted out until the app
    /// reconnected. Asking the notification centre at send time costs one cheap
    /// async call and is always current (#155).
    private func canNotify() async -> Bool {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        switch settings.authorizationStatus {
        case .authorized, .provisional, .ephemeral:
            return true
        default:
            return false
        }
    }

    func sendFiringComplete(profileName: String, peakTempC: Double, unit: String) {
        // Formatted through the shared formatter so the notification agrees with
        // the rest of the app; the body used to hardcode °C regardless of the
        // tempUnit setting (#146).
        let peak = Formatters.formatTemp(peakTempC, unit: unit)
        Task { @MainActor in
            guard await canNotify() else { return }
            guard UIApplication.shared.applicationState != .active else { return }

            let content = UNMutableNotificationContent()
            content.title = "Firing Complete"
            content.body = "\(profileName) finished successfully. Peak temp: \(peak)"
            content.sound = .default
            content.interruptionLevel = .timeSensitive

            let request = UNNotificationRequest(
                identifier: UUID().uuidString, content: content, trigger: nil
            )
            try? await UNUserNotificationCenter.current().add(request)
        }
    }

    func sendFiringError(profileName: String) {
        Task { @MainActor in
            guard await canNotify() else { return }
            guard UIApplication.shared.applicationState != .active else { return }

            let content = UNMutableNotificationContent()
            content.title = "Kiln Error"
            content.body = "\(profileName) encountered an error. Check kiln immediately."
            content.sound = .defaultCritical
            content.interruptionLevel = .timeSensitive

            let request = UNNotificationRequest(
                identifier: UUID().uuidString, content: content, trigger: nil
            )
            try? await UNUserNotificationCenter.current().add(request)
        }
    }
}
