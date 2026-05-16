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

/// Lightweight envelope used to sniff a frame's `type` before full decoding.
struct WSTypeEnvelope: Decodable {
    let type: String
}

enum OTAEvent: Sendable {
    case progress(Double)
    case complete
    case failed(String)
}

/// Decodes ota_progress / ota_complete / ota_error frames.
struct OTAWebSocketMessage: Decodable {
    struct Payload: Decodable {
        let phase: String?
        let percent: Double?
        let message: String?
    }
    let type: String
    let data: Payload

    var event: OTAEvent? {
        switch type {
        case "ota_progress": return .progress(data.percent ?? 0)
        case "ota_complete": return .complete
        case "ota_error": return .failed(data.message ?? "Update failed")
        default: return nil
        }
    }
}
