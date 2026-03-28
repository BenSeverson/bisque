import Foundation

struct FiringProfile: Codable, Identifiable, Hashable {
    let id: String
    var name: String
    var description: String
    var segments: [FiringSegment]
    var maxTemp: Double
    var estimatedDuration: Double // minutes
}
