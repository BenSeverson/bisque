import SwiftUI

enum FiringStatus: String, Codable, CaseIterable {
    case idle, heating, holding, cooling, complete, error, paused, autotune

    var color: Color {
        switch self {
        case .heating:  return Color(red: 1.0, green: 0.65, blue: 0.0)    // #FFA500
        case .holding:  return Color(red: 1.0, green: 1.0, blue: 0.0)     // #FFFF00
        case .cooling:  return Color(red: 0.29, green: 0.56, blue: 0.85)  // #4A90D9
        case .error:    return Color(red: 1.0, green: 0.23, blue: 0.19)   // #FF3B30
        case .complete: return Color(red: 0.19, green: 0.82, blue: 0.35)  // #30D158
        case .paused:   return Color(red: 1.0, green: 1.0, blue: 0.0)     // #FFFF00
        case .idle:     return .secondary
        case .autotune: return Color(red: 1.0, green: 0.65, blue: 0.0)    // #FFA500
        }
    }

    var label: String {
        rawValue.capitalized
    }
}
