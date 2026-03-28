import Foundation

struct KilnSettings: Codable {
    var tempUnit: String        // "C" or "F"
    var maxSafeTemp: Double
    var alarmEnabled: Bool
    var autoShutdown: Bool
    var notificationsEnabled: Bool
    var tcOffsetC: Double
    var webhookUrl: String
    var apiToken: String?       // write-only: only sent when changing
    var apiTokenSet: Bool?      // read-only: whether token is set
    var elementWatts: Double
    var electricityCostKwh: Double

    static let `default` = KilnSettings(
        tempUnit: "C", maxSafeTemp: 1300, alarmEnabled: true,
        autoShutdown: true, notificationsEnabled: true, tcOffsetC: 0,
        webhookUrl: "", apiToken: nil, apiTokenSet: false,
        elementWatts: 2400, electricityCostKwh: 0.12
    )
}
