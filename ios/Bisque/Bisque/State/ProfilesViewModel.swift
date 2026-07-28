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

    /// Derive the id for a duplicated profile.
    ///
    /// The firmware's NVS key is the first 15 characters of the id with anything
    /// outside `[A-Za-z0-9_]` replaced by `_`, and a save whose key collides with
    /// a different stored id is rejected with a 409. Appending a suffix therefore
    /// never produced a distinct key for any id 15 chars or longer, so
    /// duplicating a cone-fire or builder profile always failed on hardware.
    /// The unique token goes first so it lands inside those 15 characters, and
    /// so the firmware's 40-char id field truncates the tail rather than the
    /// part that makes the key unique.
    static func makeDuplicateId(_ sourceId: String) -> String {
        let token = String(Int(Date().timeIntervalSince1970 * 1000), radix: 36)
        let suffix = String(Int.random(in: 0..<1_679_616), radix: 36) // 4 base-36 chars
        return String("c\(token)\(suffix)-\(sourceId)".prefix(39))
    }

    func duplicateProfile(_ profile: FiringProfile, using client: KilnAPIClient, store: KilnStore) async {
        let copy = FiringProfile(
            id: Self.makeDuplicateId(profile.id),
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

    /// Ids reach URL paths, NVS keys, and filenames. Imported JSON is arbitrary,
    /// so anything outside this set is rejected at the door rather than escaped
    /// at each use site (#152). Matches the firmware's NVS-key-safe convention:
    /// ASCII letters, digits, dash, underscore.
    ///
    /// Spelled out rather than built from `CharacterSet.alphanumerics`, which
    /// is Unicode-aware and accepts `é`, `٣` and friends. The firmware's
    /// `make_nvs_key` only recognises ASCII `[a-zA-Z0-9_]` and rewrites
    /// everything else to `_`, and `handle_delete_profile` compares the raw
    /// request URI verbatim — so a non-ASCII id would be sent percent-encoded,
    /// match nothing, and return `ok: true` while the profile stayed put and
    /// reappeared on the next refresh.
    private static let allowedIdCharacters = CharacterSet(
        charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    )

    static func isValidProfileId(_ id: String) -> Bool {
        !id.isEmpty && id.count <= 64
            && id.unicodeScalars.allSatisfy { allowedIdCharacters.contains($0) }
    }

    func importProfile(from data: Data, using client: KilnAPIClient, store: KilnStore) async {
        do {
            let profile = try JSONDecoder().decode(FiringProfile.self, from: data)
            guard Self.isValidProfileId(profile.id) else {
                self.error = "This profile has an invalid id. Only letters, digits, - and _ are allowed."
                return
            }
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
