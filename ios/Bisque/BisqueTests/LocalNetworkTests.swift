import XCTest

@testable import Bisque

/// `LocalNetwork.requiresPermission` decides whether a failed connection gets
/// blamed on the local-network permission (#148). Both mistakes are visible to
/// the user: a false negative strands someone who denied the prompt with no
/// hint, a false positive tells someone on a public address to go check a
/// setting that has nothing to do with it.
///
/// These cases were run by hand while #266 was written; they live here now.
final class LocalNetworkTests: XCTestCase {
    private func assertLocal(
        _ hosts: [String], _ expected: Bool, line: UInt = #line
    ) {
        for host in hosts {
            XCTAssertEqual(
                LocalNetwork.requiresPermission(host: host), expected,
                "\(host)", line: line)
        }
    }

    func testLoopbackNeedsNoPermission() {
        // The simulator's mock server lives here; the hint would be noise.
        assertLocal(["localhost", "LocalHost", "app.localhost", "127.0.0.1", "127.1.2.3", "::1", "[::1]"], false)
    }

    func testPrivateIPv4RangesAreLocal() {
        assertLocal(
            ["10.0.0.1", "10.255.255.254", "172.16.0.1", "172.31.255.254",
             "192.168.1.50", "169.254.10.1"],
            true)
    }

    /// 172.0.0.0/8 is public apart from the 172.16/12 block, so the second
    /// octet is what decides it.
    func testAddressesOutsideThePrivateRangesAreNotLocal() {
        assertLocal(["8.8.8.8", "172.15.0.1", "172.32.0.1", "192.169.1.1", "169.253.0.1"], false)
    }

    func testLinkLocalAndUniqueLocalIPv6AreLocal() {
        assertLocal(["fe80::1", "FE80::1", "fe80::1%en0", "[fe80::1%en0]", "fc00::1", "fd12:3456::1"], true)
    }

    /// fec0::/10 is deprecated (RFC 3879) and no router hands it out, but a
    /// host using one is on the LAN, and the rule is that only an explicitly
    /// routable address is confidently non-local.
    func testDeprecatedSiteLocalIPv6IsStillLocal() {
        assertLocal(["fec0::1", "feff::1"], true)
    }

    func testGlobalIPv6IsNotLocal() {
        assertLocal(["2001:4860:4860::8888", "[2001:db8::1]"], false)
    }

    /// A name says nothing about the address behind it, and routers hand out
    /// far more LAN suffixes than any allow-list could cover, so names bias
    /// toward the hint. `.local` is the one this app actually ships.
    func testHostnamesAreTreatedAsLocal() {
        assertLocal(
            ["bisque.local", "bisque", "kiln.lan", "kiln.home.arpa",
             "kiln.fritz.box", "kiln.internal", "kiln.example.com"],
            true)
    }

    func testBlankHostNeedsNoPermission() {
        assertLocal(["", "   "], false)
    }

    func testSurroundingWhitespaceDoesNotChangeTheVerdict() {
        assertLocal([" 127.0.0.1 "], false)
        assertLocal([" 192.168.1.50 "], true)
    }

    /// Four numeric parts or it is a name, not a dotted quad.
    func testMalformedDottedQuadsFallThroughToTheNameBranch() {
        assertLocal(["192.168.1", "192.168.1.50.1", "192.168.1.256", "10.0.0.a"], true)
    }
}
