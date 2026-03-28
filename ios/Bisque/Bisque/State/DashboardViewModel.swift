import SwiftUI

@MainActor @Observable
final class DashboardViewModel {
    var selectedProfileId: String?
    var delayMinutes: Int = 0
    var isStarting = false
    var isPausing = false
    var isStopping = false
    var actionError: String?

    func startFiring(using client: KilnAPIClient, store: KilnStore) async {
        guard let profileId = selectedProfileId else { return }
        isStarting = true
        actionError = nil

        do {
            _ = try await client.startFiring(profileId: profileId, delayMinutes: delayMinutes)
            store.clearTemperatureHistory()
            let name = store.profiles.first(where: { $0.id == profileId })?.name ?? "Unknown"
            store.startLiveActivity(profileName: name)
            isStarting = false
        } catch {
            actionError = error.localizedDescription
            isStarting = false
        }
    }

    func pauseFiring(using client: KilnAPIClient) async {
        isPausing = true
        actionError = nil
        do {
            _ = try await client.pauseFiring()
            isPausing = false
        } catch {
            actionError = error.localizedDescription
            isPausing = false
        }
    }

    func stopFiring(using client: KilnAPIClient, store: KilnStore) async {
        isStopping = true
        actionError = nil
        do {
            _ = try await client.stopFiring()
            store.clearTemperatureHistory()
            isStopping = false
        } catch {
            actionError = error.localizedDescription
            isStopping = false
        }
    }

    func skipSegment(using client: KilnAPIClient) async {
        actionError = nil
        do {
            _ = try await client.skipSegment()
        } catch {
            actionError = error.localizedDescription
        }
    }

    /// Compute the full profile path for charting
    func computeProfilePath(for profile: FiringProfile?) -> [TemperatureDataPoint] {
        guard let profile = profile else { return [] }

        var path: [TemperatureDataPoint] = []
        var currentTime: Double = 0
        var currentTemp: Double = 20

        path.append(TemperatureDataPoint(time: 0, temp: 20, target: 20))

        for segment in profile.segments {
            let tempDifference = segment.targetTemp - currentTemp
            let rampTimeHours = abs(tempDifference) / abs(segment.rampRate)
            let rampTimeMinutes = rampTimeHours * 60

            let steps = max(10, Int(rampTimeMinutes / 5))
            for i in 1...steps {
                let progress = Double(i) / Double(steps)
                let stepTime = currentTime + rampTimeMinutes * progress
                let stepTemp = currentTemp + tempDifference * progress
                path.append(TemperatureDataPoint(
                    time: stepTime, temp: round(stepTemp), target: round(stepTemp)
                ))
            }

            currentTime += rampTimeMinutes
            currentTemp = segment.targetTemp

            if segment.holdTime > 0 {
                path.append(TemperatureDataPoint(
                    time: currentTime + segment.holdTime,
                    temp: segment.targetTemp,
                    target: segment.targetTemp
                ))
                currentTime += segment.holdTime
            }
        }

        return path
    }
}
