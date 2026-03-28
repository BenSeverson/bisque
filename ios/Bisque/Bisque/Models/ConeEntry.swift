import Foundation

struct ConeEntry: Codable, Identifiable {
    let id: Int
    let name: String
    let slowTempC: Double
    let mediumTempC: Double
    let fastTempC: Double
}
