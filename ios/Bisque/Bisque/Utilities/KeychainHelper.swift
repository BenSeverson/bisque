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

        return String(data: data, encoding: .utf8)
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
