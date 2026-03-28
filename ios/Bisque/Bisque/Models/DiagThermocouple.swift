import Foundation

struct DiagThermocouple: Codable {
    let temperatureC: Double
    let internalTempC: Double
    let fault: Bool
    let openCircuit: Bool
    let shortGnd: Bool
    let shortVcc: Bool
    let readingAgeMs: Int
    let temperatureAdjustedC: Double
    let tcOffsetC: Double
}
