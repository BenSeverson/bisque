import SwiftUI

@MainActor @Observable
final class DashboardViewModel {
    var selectedProfileId: String?
    var delayMinutes: Int = 0
    var isStarting = false
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
        actionError = nil
        do {
            _ = try await client.pauseFiring()
        } catch {
            actionError = error.localizedDescription
        }
    }

    func stopFiring(using client: KilnAPIClient, store: KilnStore) async {
        actionError = nil
        do {
            _ = try await client.stopFiring()
            store.clearTemperatureHistory()
        } catch {
            actionError = error.localizedDescription
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

        /* Budget shared across the whole path, not handed to each segment.
           The firmware allows 16 segments, so a per-segment allowance of
           maxProfilePathPoints would admit ~32,000 freshly identified LineMarks
           on every recompute — defeating the cap rather than enforcing it. */
        let computableSegments = profile.segments.filter(\.isComputable).count
        let perSegmentBudget = max(2, maxProfilePathPoints / max(1, computableSegments))

        for segment in profile.segments {
            /* Skipped only when the arithmetic genuinely cannot run: a zero or
               non-finite rate makes rampTimeMinutes infinite, and
               `Int(Double.infinity)` is a fatal error in Swift, not a garbage
               value — so charting such a profile crashed the app outright (#143).

               Deliberately `isComputable` and not `validationError`: the latter
               is the builder's stricter save policy, and applying it here would
               drop slow-but-legal segments the controller has stored and is
               firing, shifting every later segment's temperature and timing. */
            guard segment.isComputable else { continue }

            let tempDifference = segment.targetTemp - currentTemp
            let rampTimeHours = abs(tempDifference) / abs(segment.rampRate)
            let rampTimeMinutes = rampTimeHours * 60

            // Never below 1: `1...steps` traps on an empty range.
            let steps = max(1, min(perSegmentBudget, max(10, Int(rampTimeMinutes / 5))))
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
