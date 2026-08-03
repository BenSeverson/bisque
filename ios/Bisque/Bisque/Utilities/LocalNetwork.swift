import Foundation

/// Classification of the kiln's address, used to decide whether a connection
/// failure is worth blaming on the local-network privacy permission (#148).
///
/// iOS exposes no API for querying that permission's state, so the app cannot
/// say "you denied it" — it can only tell that the host is one the permission
/// governs and offer the Settings toggle as a thing to check. Loopback (the
/// simulator's mock server) is deliberately excluded: it needs no permission,
/// so the hint there would be pure noise.
enum LocalNetwork {
    /// True when reaching `host` requires the local-network permission.
    static func requiresPermission(host: String) -> Bool {
        let host = host.trimmingCharacters(in: .whitespaces).lowercased()
        guard !host.isEmpty else { return false }

        // Strip an IPv6 literal's brackets and any zone id ("fe80::1%en0").
        let bare = host.trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
            .split(separator: "%", maxSplits: 1).first.map(String.init) ?? host

        if bare == "localhost" || bare.hasSuffix(".localhost") { return false }

        if let v4 = ipv4Octets(bare) {
            switch v4.0 {
            case 127: return false                      // loopback
            case 10: return true                        // 10.0.0.0/8
            case 172: return (16...31).contains(v4.1)   // 172.16.0.0/12
            case 192: return v4.1 == 168                // 192.168.0.0/16
            case 169: return v4.1 == 254                // 169.254.0.0/16 link-local
            default: return false                       // routable — WAN, not LAN
            }
        }

        if bare.contains(":") {
            // IPv6 literal: ::1 is loopback, fe80::/10 link-local and fc00::/7
            // unique-local are LAN, everything else is routable.
            if bare == "::1" { return false }
            return bare.hasPrefix("fe8") || bare.hasPrefix("fe9")
                || bare.hasPrefix("fea") || bare.hasPrefix("feb")
                || bare.hasPrefix("fc") || bare.hasPrefix("fd")
        }

        // Names: ".local" is mDNS, and a single-label name ("kiln") resolves on
        // the LAN too. A dotted public name does not.
        return bare.hasSuffix(".local") || !bare.contains(".")
    }

    /// Parses a dotted-quad, returning nil for anything that is not one.
    private static func ipv4Octets(_ host: String) -> (Int, Int, Int, Int)? {
        let parts = host.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 4 else { return nil }
        let octets = parts.compactMap { Int($0) }
        guard octets.count == 4, octets.allSatisfy({ (0...255).contains($0) }) else { return nil }
        return (octets[0], octets[1], octets[2], octets[3])
    }
}
