import Foundation

struct FiringProgress: Codable {
    var isActive: Bool
    var profileId: String?
    var startTime: Double?
    var currentTemp: Double
    var targetTemp: Double
    var currentSegment: Int
    var totalSegments: Int
    var elapsedTime: Double      // seconds
    var estimatedTimeRemaining: Double  // seconds
    var status: String

    var firingStatus: FiringStatus {
        FiringStatus(rawValue: status) ?? .idle
    }

    static let idle = FiringProgress(
        isActive: false, profileId: nil, startTime: nil,
        currentTemp: 20, targetTemp: 20, currentSegment: 0,
        totalSegments: 0, elapsedTime: 0, estimatedTimeRemaining: 0,
        status: "idle"
    )
}
