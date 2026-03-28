import ActivityKit
import Foundation

struct FiringActivityAttributes: ActivityAttributes {
    let profileName: String
    let startTime: Date

    struct ContentState: Codable, Hashable {
        let currentTemp: Double
        let targetTemp: Double
        let status: String
        let currentSegment: Int
        let totalSegments: Int
        let progress: Double          // 0.0 - 1.0
        let estimatedSecondsRemaining: Int
    }
}
