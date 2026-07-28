import Foundation
import OSLog
import Security

enum KeychainHelper {
    private static let service = "com.bisque.kiln-controller"
    private static let log = Logger(subsystem: "com.bisque.kiln-controller", category: "keychain")

    /// Stores `value` under `key`, returning whether it was actually written.
    ///
    /// The result used to be discarded, so a failed `SecItemAdd` left the app
    /// believing the token was saved; on the next launch `KilnConnection`
    /// restored `nil` and the user was locked out with "Authentication
    /// required" and no way to tell why (#151).
    ///
    /// `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` keeps the item
    /// readable to background work after the first unlock, while the
    /// `ThisDeviceOnly` suffix stops it migrating to another device through an
    /// encrypted backup restore.
    @discardableResult
    static func save(key: String, value: String) -> Bool {
        guard let data = value.data(using: .utf8) else {
            log.error("Refusing to store non-UTF8 value for key \(key, privacy: .public)")
            return false
        }

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]

        // Delete existing
        SecItemDelete(query as CFDictionary)

        // Add new
        var addQuery = query
        addQuery[kSecValueData as String] = data
        addQuery[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly

        let status = SecItemAdd(addQuery as CFDictionary, nil)
        guard status == errSecSuccess else {
            log.error(
                "Keychain save failed for key \(key, privacy: .public): OSStatus \(status)"
            )
            return false
        }
        return true
    }

    static func load(key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess, let data = result as? Data else {
            return nil
        }

        migrateAccessibility(key: key)
        return String(data: data, encoding: .utf8)
    }

    /// Re-apply the hardened accessibility class to an item written by an
    /// earlier build.
    ///
    /// `kSecAttrAccessible` is only set by `save`, and an upgrading user never
    /// calls it — the token is loaded at startup and never rewritten. Without
    /// this, everyone already running the app keeps the migratable default
    /// forever and the hardening only reaches people who happen to re-enter
    /// their token. Idempotent, and cheap enough to run on each load.
    private static func migrateAccessibility(key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        let attributes: [String: Any] = [
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        ]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status != errSecSuccess {
            log.error(
                "Keychain accessibility migration failed for key \(key, privacy: .public): OSStatus \(status)"
            )
        }
    }

    static func delete(key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
