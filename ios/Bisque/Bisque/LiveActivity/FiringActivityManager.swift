@preconcurrency import ActivityKit
import Foundation
import OSLog

@MainActor @Observable
final class FiringActivityManager {
    private var currentActivity: Activity<FiringActivityAttributes>?
    private let log = Logger(subsystem: "com.bisque.kiln-controller", category: "liveactivity")

    /// How long a posted reading stays presentable before ActivityKit renders it
    /// as stale.
    ///
    /// The app has no background modes and no ActivityKit push token, so iOS
    /// suspends the WebSocket within seconds of backgrounding and there is
    /// nothing to update the activity until the app is opened again (#147).
    /// With no `staleDate` the lock screen kept showing that last temperature as
    /// current — indefinitely, across an 8–12 hour firing. Wrong and confident is
    /// worse than visibly out of date, for a number an operator may act on.
    ///
    /// The firmware broadcasts every second, so any gap beyond a few seconds is
    /// already abnormal; 90s is loose enough to ride out a Wi-Fi blip while the
    /// app is foregrounded without flickering to stale.
    private static let staleAfter: TimeInterval = 90

    private static func staleDate(from now: Date = Date()) -> Date {
        now.addingTimeInterval(staleAfter)
    }

    func start(profileName: String) {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }

        let attributes = FiringActivityAttributes(
            profileName: profileName,
            startTime: Date()
        )

        let initialState = FiringActivityAttributes.ContentState(
            currentTemp: 20,
            targetTemp: 0,
            status: "heating",
            currentSegment: 0,
            totalSegments: 0,
            progress: 0,
            estimatedSecondsRemaining: 0
        )

        do {
            currentActivity = try Activity.request(
                attributes: attributes,
                content: .init(state: initialState, staleDate: Self.staleDate()),
                pushType: nil
            )
        } catch {
            log.error("Failed to start Live Activity: \(error.localizedDescription, privacy: .public)")
        }
    }

    func update(
        temp: Double, target: Double, status: String,
        segment: Int, totalSegments: Int, remaining: Int,
        elapsed: Double, estimatedTotal: Double
    ) {
        guard let activity = currentActivity else { return }

        let progress = estimatedTotal > 0 ? min(1.0, elapsed / estimatedTotal) : 0

        let state = FiringActivityAttributes.ContentState(
            currentTemp: temp,
            targetTemp: target,
            status: status,
            currentSegment: segment,
            totalSegments: totalSegments,
            progress: progress,
            estimatedSecondsRemaining: remaining
        )

        Task {
            await activity.update(.init(state: state, staleDate: Self.staleDate()))
        }
    }

    func end(status: String) {
        guard let activity = currentActivity else { return }
        self.currentActivity = nil

        let finalState = FiringActivityAttributes.ContentState(
            currentTemp: 0,
            targetTemp: 0,
            status: status,
            currentSegment: 0,
            totalSegments: 0,
            progress: 1.0,
            estimatedSecondsRemaining: 0
        )

        Task {
            /* No staleDate on the terminal content: "Complete" is not a
               reading that decays, and marking it stale after 90s would make a
               finished firing look like a lost connection. */
            await activity.end(.init(state: finalState, staleDate: nil), dismissalPolicy: .after(.now + 300))
        }
    }
}
