import UserNotifications
import UIKit

@MainActor
final class NotificationManager {
    private var hasPermission = false

    init() {
        Task { @MainActor in
            await requestPermission()
        }
    }

    func requestPermission() async {
        do {
            hasPermission = try await UNUserNotificationCenter.current().requestAuthorization(
                options: [.alert, .sound, .badge]
            )
        } catch {
            hasPermission = false
        }
    }

    func sendFiringComplete(profileName: String, peakTemp: Double) {
        guard hasPermission else { return }
        guard UIApplication.shared.applicationState != .active else { return }

        let content = UNMutableNotificationContent()
        content.title = "Firing Complete"
        content.body = "\(profileName) finished successfully. Peak temp: \(Int(peakTemp))°C"
        content.sound = .default
        content.interruptionLevel = .timeSensitive

        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    func sendFiringError(profileName: String) {
        guard hasPermission else { return }
        guard UIApplication.shared.applicationState != .active else { return }

        let content = UNMutableNotificationContent()
        content.title = "Kiln Error"
        content.body = "\(profileName) encountered an error. Check kiln immediately."
        content.sound = .defaultCritical
        content.interruptionLevel = .timeSensitive

        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }
}
