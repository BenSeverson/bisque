import Foundation

struct WebSocketMessage: Codable {
    let type: String
    let data: TempUpdateData
}

struct TempUpdateData: Codable {
    let currentTemp: Double
    let targetTemp: Double
    let status: String
    let currentSegment: Int
    let totalSegments: Int
    let elapsedTime: Double
    let estimatedTimeRemaining: Double
    let isActive: Bool
}
