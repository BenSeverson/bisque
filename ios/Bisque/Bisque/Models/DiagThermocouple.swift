import Foundation

struct DiagThermocouple: Codable {
    let temperatureC: Double
    let internalTempC: Double
    let fault: Bool
    let openCircuit: Bool
    let shortGnd: Bool
    let shortVcc: Bool
    /// Hot junction outside the probe type's measurable range, so the reported
    /// temperature is a clamp rather than a measurement. Optional because a kiln
    /// on firmware older than the MAX31856 driver never sends it.
    let outOfRange: Bool?
    let readingAgeMs: Int
    let temperatureAdjustedC: Double
    let tcOffsetC: Double
}
