import Foundation

struct SystemInfo: Codable {
    let firmware: String
    let model: String
    let uptimeSeconds: Double
    let freeHeap: Int
    /// Free internal SRAM. `freeHeap` includes the 8MB of PSRAM, so it stays in
    /// the megabytes while this is the pool that actually constrains the device.
    let freeInternalHeap: Int
    let emergencyStop: Bool
    let lastErrorCode: Int
    let elementHoursS: Double
    let spiffsTotal: Int
    let spiffsUsed: Int
    let boardTempC: Double
}
