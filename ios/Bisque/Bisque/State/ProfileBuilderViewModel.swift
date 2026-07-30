import SwiftUI

@MainActor @Observable
final class ProfileBuilderViewModel {
    var name: String = ""
    var description: String = ""
    var segments: [FiringSegment] = []
    var error: String?
    var isSaving = false

    // Cone fire wizard
    var coneTable: [ConeEntry] = []
    var selectedConeId: Int?
    var coneSpeed: Int = 1          // 0=slow, 1=medium, 2=fast
    var conePreheat: Bool = true
    var coneSlowCool: Bool = false

    /// Filtered to finite values: this is rendered via `Int(_:)`, which traps on
    /// infinity rather than producing a wrong number (#143).
    var maxTemp: Double {
        segments.map(\.targetTemp).filter(\.isFinite).max() ?? 0
    }

    /// Total planned minutes, skipping segments that cannot be computed.
    ///
    /// Dividing by `abs(rampRate)` makes this infinite for a rate of 0, and
    /// `JSONEncoder` refuses to encode a non-finite `Double` — so the profile
    /// save failed with an `EncodingError` that named neither the segment nor
    /// the field (#143). Skipping keeps the figure finite; `validationError` is
    /// what stops the save, with a message that says which segment is wrong.
    var estimatedDuration: Double {
        var totalMinutes: Double = 0
        var currentTemp: Double = 20
        for segment in segments where segment.validationError == nil {
            let diff = abs(segment.targetTemp - currentTemp)
            let rampMinutes = (diff / abs(segment.rampRate)) * 60
            totalMinutes += rampMinutes + segment.holdTime
            currentTemp = segment.targetTemp
        }
        return totalMinutes
    }

    /// First reason the current draft cannot be saved, or nil if it is valid.
    var validationError: String? {
        if name.isEmpty || segments.isEmpty {
            return "Profile needs a name and at least one segment"
        }
        return segments.compactMap(\.validationError).first
    }

    func loadForEditing(_ profile: FiringProfile) {
        name = profile.name
        description = profile.description
        segments = profile.segments
    }

    func addSegment() {
        let lastTemp = segments.last?.targetTemp ?? 20
        segments.append(FiringSegment(
            id: UUID().uuidString,
            name: "Segment \(segments.count + 1)",
            rampRate: 100,
            targetTemp: lastTemp + 100,
            holdTime: 0
        ))
    }

    func removeSegment(at index: Int) {
        guard segments.indices.contains(index) else { return }
        segments.remove(at: index)
    }

    func moveSegment(from source: IndexSet, to destination: Int) {
        segments.move(fromOffsets: source, toOffset: destination)
    }

    func saveProfile(existingId: String?, using client: KilnAPIClient, store: KilnStore) async {
        /* Covers the name/segment-count check and every per-segment bound. The
           ramp-rate case is the one that mattered: it used to reach the encoder
           as an infinite estimatedDuration and fail with an EncodingError naming
           nothing the user could act on (#143). */
        if let problem = validationError {
            error = problem
            return
        }

        isSaving = true
        error = nil

        let profile = FiringProfile(
            id: existingId ?? UUID().uuidString,
            name: name,
            description: description,
            segments: segments,
            maxTemp: maxTemp,
            estimatedDuration: estimatedDuration
        )

        do {
            let result = try await client.saveProfile(profile)
            let saved = profile.copyWithId(result.id)
            if let index = store.profiles.firstIndex(where: { $0.id == existingId }) {
                store.profiles[index] = saved
            } else {
                store.profiles.append(saved)
            }
            isSaving = false
        } catch {
            self.error = error.localizedDescription
            isSaving = false
        }
    }

    func loadConeTable(using client: KilnAPIClient) async {
        do {
            coneTable = try await client.getConeTable()
        } catch {
            self.error = error.localizedDescription
        }
    }

    func generateConeFire(using client: KilnAPIClient) async -> FiringProfile? {
        guard let coneId = selectedConeId else {
            error = "Select a cone"
            return nil
        }

        do {
            let profile = try await client.generateConeFire(ConeFireRequest(
                coneId: coneId, speed: coneSpeed,
                preheat: conePreheat, slowCool: coneSlowCool, save: false
            ))
            return profile
        } catch {
            self.error = error.localizedDescription
            return nil
        }
    }

    func reset() {
        name = ""
        description = ""
        segments = []
        error = nil
        selectedConeId = nil
        coneSpeed = 1
        conePreheat = true
        coneSlowCool = false
    }
}
