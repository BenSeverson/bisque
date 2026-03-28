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

    var maxTemp: Double {
        segments.map(\.targetTemp).max() ?? 0
    }

    var estimatedDuration: Double {
        var totalMinutes: Double = 0
        var currentTemp: Double = 20
        for segment in segments {
            let diff = abs(segment.targetTemp - currentTemp)
            let rampMinutes = (diff / abs(segment.rampRate)) * 60
            totalMinutes += rampMinutes + segment.holdTime
            currentTemp = segment.targetTemp
        }
        return totalMinutes
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
        guard !name.isEmpty, !segments.isEmpty else {
            error = "Profile needs a name and at least one segment"
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
            let saved = FiringProfile(id: result.id, name: profile.name,
                                      description: profile.description,
                                      segments: profile.segments,
                                      maxTemp: profile.maxTemp,
                                      estimatedDuration: profile.estimatedDuration)
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
