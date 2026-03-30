import Foundation

struct FiringSegment: Codable, Identifiable, Hashable {
    let id: String
    var name: String
    var rampRate: Double    // degrees per hour
    var targetTemp: Double  // degrees C
    var holdTime: Double    // minutes (0 = hold indefinitely)

    var formattedDescription: String {
        "\(rampRate > 0 ? "+" : "")\(Int(rampRate))°C/hr → \(Int(targetTemp))°C\(holdTime > 0 ? ", hold \(Int(holdTime))m" : "")"
    }
}
