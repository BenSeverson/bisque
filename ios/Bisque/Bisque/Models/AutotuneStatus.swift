import Foundation

struct AutotuneStatus: Codable {
    let state: String           // "running", "idle", "stopped"
    let elapsedTime: Double
    let targetTemp: Double
    let currentTemp: Double
    let currentGains: PIDGains

    struct PIDGains: Codable {
        let kp: Double
        let ki: Double
        let kd: Double
    }
}
