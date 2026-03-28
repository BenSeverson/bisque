import Foundation

struct TemperatureDataPoint: Identifiable {
    let id = UUID()
    let time: Double    // minutes
    let temp: Double
    let target: Double
}
