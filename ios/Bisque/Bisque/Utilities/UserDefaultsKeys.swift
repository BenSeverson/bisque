import Foundation

enum UserDefaultsKeys {
    static let kilnPort = "kilnPort"
    static let lastConnectedHost = "lastConnectedHost"
    /// Bonjour instance name of the kiln behind `lastConnectedHost`, so a new
    /// DHCP lease can be resolved rather than re-picked by hand (#153).
    static let lastConnectedServiceName = "lastConnectedServiceName"
    static let tempUnit = "tempUnit"
}
