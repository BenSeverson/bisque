import SwiftUI
import UniformTypeIdentifiers

@MainActor @Observable
final class ProfilesViewModel {
    var isLoading = false
    var error: String?

    func deleteProfile(id: String, using client: KilnAPIClient, store: KilnStore) async {
        do {
            _ = try await client.deleteProfile(id: id)
            store.profiles.removeAll(where: { $0.id == id })
        } catch {
            self.error = error.localizedDescription
        }
    }

    func duplicateProfile(_ profile: FiringProfile, using client: KilnAPIClient, store: KilnStore) async {
        let copy = FiringProfile(
            id: "\(profile.id)-copy-\(Int(Date().timeIntervalSince1970))",
            name: "\(profile.name) (Copy)",
            description: profile.description,
            segments: profile.segments,
            maxTemp: profile.maxTemp,
            estimatedDuration: profile.estimatedDuration
        )

        do {
            let result = try await client.saveProfile(copy)
            var saved = copy
            saved = FiringProfile(id: result.id, name: copy.name, description: copy.description,
                                  segments: copy.segments, maxTemp: copy.maxTemp,
                                  estimatedDuration: copy.estimatedDuration)
            store.profiles.append(saved)
        } catch {
            self.error = error.localizedDescription
        }
    }

    func importProfile(from data: Data, using client: KilnAPIClient, store: KilnStore) async {
        do {
            let profile = try JSONDecoder().decode(FiringProfile.self, from: data)
            let result = try await client.importProfile(profile)
            let imported = FiringProfile(id: result.id, name: profile.name,
                                         description: profile.description,
                                         segments: profile.segments,
                                         maxTemp: profile.maxTemp,
                                         estimatedDuration: profile.estimatedDuration)
            store.profiles.append(imported)
        } catch {
            self.error = error.localizedDescription
        }
    }

    func exportProfileData(_ profile: FiringProfile) -> Data? {
        try? JSONEncoder().encode(profile)
    }
}
