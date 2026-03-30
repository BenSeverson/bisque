import SwiftUI
import UniformTypeIdentifiers

@MainActor @Observable
final class ProfilesViewModel {
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
            let saved = copy.copyWithId(result.id)
            store.profiles.append(saved)
        } catch {
            self.error = error.localizedDescription
        }
    }

    func importProfile(from data: Data, using client: KilnAPIClient, store: KilnStore) async {
        do {
            let profile = try JSONDecoder().decode(FiringProfile.self, from: data)
            let result = try await client.importProfile(profile)
            let imported = profile.copyWithId(result.id)
            store.profiles.append(imported)
        } catch {
            self.error = error.localizedDescription
        }
    }

    func exportProfileData(_ profile: FiringProfile) -> Data? {
        try? JSONEncoder().encode(profile)
    }
}
