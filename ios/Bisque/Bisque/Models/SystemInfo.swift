import Foundation

struct SystemInfo: Codable {
    let firmware: String
    let model: String
    let uptimeSeconds: Double
    let freeHeap: Int
    let emergencyStop: Bool
    let lastErrorCode: Int
    let elementHoursS: Double
    let spiffsTotal: Int
    let spiffsUsed: Int
    let boardTempC: Double
}
