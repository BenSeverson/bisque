import Network
import XCTest

@testable import Bisque

/// Covers the two decisions `KilnDiscovery` makes that the browse cannot:
/// whether a responder is a kiln at all, and when it is safe to show that
/// responder the API token.
final class KilnDiscoveryTests: XCTestCase {
    /// The shape `api_json.c` emits for `GET /api/v1/status`.
    private static let statusJSON = Data(
        """
        {"isActive":true,"profileId":"abc","currentTemp":812.5,"targetTemp":900,
         "currentSegment":1,"totalSegments":3,"elapsedTime":1200,
         "estimatedTimeRemaining":3600,"status":"heating",
         "thermocouple":{"temperature":812.5,"internalTemp":31,"fault":false,
         "openCircuit":false,"shortGnd":false,"shortVcc":false}}
        """.utf8)

    private static let bisqueChallenge = ["WWW-Authenticate": "Bearer realm=\"bisque\""]
    private static let printerChallenge = ["WWW-Authenticate": "Basic realm=\"printer\""]

    private func verify(
        serviceName: String = "Bisque Kiln Controller",
        apiToken: String? = nil,
        replies: [StubURLProtocol.Reply]
    ) async -> Bool? {
        StubURLProtocol.script(replies)
        return await KilnDiscovery.verify(
            host: "10.0.0.5", port: 80, serviceName: serviceName,
            apiToken: apiToken, timeout: 1, session: StubURLProtocol.makeSession())
    }

    // MARK: - Identification

    func testStatusResponseIdentifiesAnUnlockedKiln() async {
        let verdict = await verify(replies: [.init(body: Self.statusJSON)])
        XCTAssertEqual(verdict, false, "a decodable status answer is an unlocked kiln")
        XCTAssertEqual(StubURLProtocol.authorizationHeaders, [nil])
    }

    func testPlainHTTPDeviceIsNotAKiln() async {
        // A printer's web UI answers 200 to anything, including /api/v1/status.
        let verdict = await verify(
            serviceName: "Officejet Pro",
            replies: [.init(body: Data("<html>Printer</html>".utf8))])
        XCTAssertNil(verdict)
    }

    /// The instance name is not evidence on its own — plenty of things can
    /// advertise any name they like, and only the API answer settles it.
    func testDeviceNamedBisqueThatCannotSpeakTheAPIIsNotAKiln() async {
        let verdict = await verify(replies: [.init(body: Data("<html>hi</html>".utf8))])
        XCTAssertNil(verdict)
    }

    func testServerErrorIsNotAKiln() async {
        let verdict = await verify(replies: [.init(statusCode: 500)])
        XCTAssertNil(verdict)
    }

    func testTransportFailureIsNotAKiln() async {
        let verdict = await verify(
            replies: [.init(error: URLError(.cannotConnectToHost))])
        XCTAssertNil(verdict)
    }

    // MARK: - Challenges

    func testBisqueChallengeIdentifiesALockedKiln() async {
        let verdict = await verify(
            replies: [.init(statusCode: 401, headers: Self.bisqueChallenge)])
        XCTAssertEqual(verdict, true)
        XCTAssertEqual(StubURLProtocol.authorizationHeaders, [nil])
    }

    /// `httpd_resp_send_err()` preserves the header `require_auth` sets, but if
    /// that ever changes the Bonjour instance name still identifies the kiln.
    func testBisqueInstanceNameIdentifiesAKilnWhenTheChallengeIsBare() async {
        let verdict = await verify(replies: [.init(statusCode: 401)])
        XCTAssertEqual(verdict, true)
    }

    func testGenericChallengeFromAnUnrelatedDeviceIsNotAKiln() async {
        let verdict = await verify(
            serviceName: "Officejet Pro",
            replies: [.init(statusCode: 401, headers: Self.printerChallenge)])
        XCTAssertNil(verdict)
    }

    // MARK: - Token handling

    /// The regression test for the credential leak: the browse enumerates every
    /// HTTP service on the network, so a device that has not identified itself
    /// as a kiln must never be shown the token — no matter how it answers.
    func testTokenIsNeverSentToAnUnidentifiedDevice() async {
        let verdict = await verify(
            serviceName: "Officejet Pro", apiToken: "sekrit",
            replies: [.init(statusCode: 401, headers: Self.printerChallenge)])
        XCTAssertNil(verdict)
        XCTAssertEqual(
            StubURLProtocol.authorizationHeaders, [nil],
            "the probe must stop at the anonymous request, carrying no credential")
    }

    func testTokenIsNotSentToADeviceThatAnswersButIsNotAKiln() async {
        let verdict = await verify(
            apiToken: "sekrit",
            replies: [.init(body: Data("<html>hi</html>".utf8))])
        XCTAssertNil(verdict)
        XCTAssertEqual(StubURLProtocol.authorizationHeaders, [nil])
    }

    func testMatchingTokenUnlocksAChallengedKilnAnonymousRequestFirst() async {
        let verdict = await verify(
            apiToken: "sekrit",
            replies: [
                .init(statusCode: 401, headers: Self.bisqueChallenge),
                .init(body: Self.statusJSON),
            ])
        XCTAssertEqual(verdict, false)
        XCTAssertEqual(
            StubURLProtocol.authorizationHeaders, [nil, "Bearer sekrit"],
            "identification must precede the credential, never the other way round")
    }

    func testWrongTokenLeavesTheKilnLocked() async {
        let verdict = await verify(
            apiToken: "wrong",
            replies: [
                .init(statusCode: 401, headers: Self.bisqueChallenge),
                .init(statusCode: 401, headers: Self.bisqueChallenge),
            ])
        XCTAssertEqual(verdict, true)
        XCTAssertEqual(StubURLProtocol.authorizationHeaders, [nil, "Bearer wrong"])
    }

    func testEmptyTokenIsTreatedAsNoToken() async {
        let verdict = await verify(
            apiToken: "",
            replies: [.init(statusCode: 401, headers: Self.bisqueChallenge)])
        XCTAssertEqual(verdict, true)
        XCTAssertEqual(StubURLProtocol.authorizationHeaders, [nil])
    }

    // MARK: - Host formatting

    func testIPv4HostIsUsedVerbatim() {
        let host = NWEndpoint.Host.ipv4(IPv4Address("192.168.1.50")!)
        XCTAssertEqual(KilnDiscovery.urlHost(for: host), "192.168.1.50")
    }

    func testIPv6HostIsBracketed() {
        let host = NWEndpoint.Host.ipv6(IPv6Address("fd00::1")!)
        XCTAssertEqual(KilnDiscovery.urlHost(for: host), "[fd00::1]")
    }

    /// A link-local address carries a `%en0` zone that a URL can only take
    /// percent-escaped inside brackets (RFC 6874).
    func testIPv6LinkLocalZoneIsPercentEscaped() throws {
        let address = try XCTUnwrap(IPv6Address("fe80::1%en0"))
        XCTAssertEqual(
            KilnDiscovery.urlHost(for: .ipv6(address)), "[fe80::1%25en0]")
    }

    func testNamedHostIsUsedVerbatim() {
        XCTAssertEqual(
            KilnDiscovery.urlHost(for: .name("bisque.local", nil)), "bisque.local")
    }

    /// Every formatting branch has to produce something `URL` will accept, or
    /// the probe fails with `invalidURL` against a kiln that is right there.
    func testEveryFormattedHostBuildsAUsableURL() throws {
        let hosts: [NWEndpoint.Host] = [
            .ipv4(IPv4Address("192.168.1.50")!),
            .ipv6(IPv6Address("fd00::1")!),
            .ipv6(try XCTUnwrap(IPv6Address("fe80::1%en0"))),
            .name("bisque.local", nil),
        ]
        for host in hosts {
            let formatted = try XCTUnwrap(KilnDiscovery.urlHost(for: host))
            XCTAssertNotNil(
                URL(string: "http://\(formatted):80/api/v1/status"),
                "\(formatted) does not survive URL construction")
        }
    }
}
