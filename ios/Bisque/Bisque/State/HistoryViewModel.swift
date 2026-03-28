import SwiftUI

@MainActor @Observable
final class HistoryViewModel {
    var selectedRecord: HistoryRecord?
    var traceData: [TemperatureDataPoint] = []
    var isLoadingTrace = false
    var error: String?

    func loadTrace(for record: HistoryRecord, using client: KilnAPIClient) async {
        isLoadingTrace = true
        error = nil

        do {
            let csv = try await client.getHistoryTrace(recordId: record.id)
            traceData = parseCSV(csv)
            isLoadingTrace = false
        } catch {
            self.error = error.localizedDescription
            isLoadingTrace = false
        }
    }

    private func parseCSV(_ csv: String) -> [TemperatureDataPoint] {
        var points: [TemperatureDataPoint] = []
        let lines = csv.components(separatedBy: "\n")

        for line in lines.dropFirst() { // skip header
            let parts = line.components(separatedBy: ",")
            guard parts.count >= 2,
                  let timeS = Double(parts[0].trimmingCharacters(in: .whitespaces)),
                  let tempC = Double(parts[1].trimmingCharacters(in: .whitespaces)) else {
                continue
            }
            points.append(TemperatureDataPoint(
                time: timeS / 60.0, // convert seconds to minutes
                temp: tempC,
                target: 0 // trace doesn't include target
            ))
        }

        return points
    }

    func traceCSVData(for record: HistoryRecord, using client: KilnAPIClient) async -> Data? {
        do {
            let csv = try await client.getHistoryTrace(recordId: record.id)
            return csv.data(using: .utf8)
        } catch {
            return nil
        }
    }
}
