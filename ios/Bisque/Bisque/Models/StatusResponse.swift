import Foundation

struct StatusResponse: Codable {
    let isActive: Bool
    let profileId: String
    let currentTemp: Double
    let targetTemp: Double
    let currentSegment: Int
    let totalSegments: Int
    let elapsedTime: Double
    let estimatedTimeRemaining: Double
    let status: String
    let thermocouple: ThermocoupleData

    struct ThermocoupleData: Codable {
        let temperature: Double
        let internalTemp: Double
        let fault: Bool
        let openCircuit: Bool
        let shortGnd: Bool
        let shortVcc: Bool
    }
}
