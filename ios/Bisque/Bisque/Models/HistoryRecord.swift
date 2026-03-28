import Foundation

struct HistoryRecord: Codable, Identifiable, Hashable {
    let id: Int
    let startTime: Double       // Unix timestamp
    let profileName: String
    let profileId: String
    let peakTemp: Double
    let durationS: Double       // seconds
    let outcome: String         // "complete", "error", "aborted"
    let errorCode: Int

    var startDate: Date {
        Date(timeIntervalSince1970: startTime)
    }

    var isSuccess: Bool {
        outcome == "complete"
    }
}
