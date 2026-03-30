import Foundation

enum Formatters {
    /// Format seconds into "Xh Ym" string
    static func formatDuration(seconds: Double) -> String {
        let totalSeconds = Int(seconds)
        let hours = totalSeconds / 3600
        let minutes = (totalSeconds % 3600) / 60
        if hours > 0 {
            return "\(hours)h \(minutes)m"
        }
        return "\(minutes)m"
    }

    /// Format seconds into "Xh Ym Zs" string
    static func formatDurationLong(seconds: Double) -> String {
        let totalSeconds = Int(seconds)
        let hours = totalSeconds / 3600
        let minutes = (totalSeconds % 3600) / 60
        let secs = totalSeconds % 60
        if hours > 0 {
            return "\(hours)h \(minutes)m \(secs)s"
        } else if minutes > 0 {
            return "\(minutes)m \(secs)s"
        }
        return "\(secs)s"
    }

    /// Format temperature with unit
    static func formatTemp(_ tempC: Double, unit: String = "C") -> String {
        let temp = unit == "F" ? TemperatureConverter.cToF(tempC) : tempC
        return "\(Int(round(temp)))°\(unit)"
    }

    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .medium
        f.timeStyle = .short
        return f
    }()

    /// Format a Unix timestamp to a readable date string
    static func formatDate(_ timestamp: Double) -> String {
        formatDate(Date(timeIntervalSince1970: timestamp))
    }

    /// Format a Date to a readable date string
    static func formatDate(_ date: Date) -> String {
        dateFormatter.string(from: date)
    }
}
