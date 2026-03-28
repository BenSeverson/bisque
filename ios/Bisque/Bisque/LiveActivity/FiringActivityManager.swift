@preconcurrency import ActivityKit
import Foundation

@MainActor @Observable
final class FiringActivityManager {
    private var currentActivity: Activity<FiringActivityAttributes>?

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
                content: .init(state: initialState, staleDate: nil),
                pushType: nil
            )
        } catch {
            print("[LiveActivity] Failed to start: \(error)")
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
            await activity.update(.init(state: state, staleDate: nil))
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
            await activity.end(.init(state: finalState, staleDate: nil), dismissalPolicy: .after(.now + 300))
        }
    }
}
