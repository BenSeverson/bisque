import XCTest

@testable import Bisque

/// Covers what `KilnConnection` remembers between launches, and the one thing
/// it does about a remembered address that has gone stale (#153).
@MainActor
final class KilnConnectionTests: XCTestCase {
    private var defaults: UserDefaults!
    private var suiteName: String!

    override func setUp() {
        super.setUp()
        suiteName = "KilnConnectionTests.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suiteName)
        defaults = nil
        suiteName = nil
        super.tearDown()
    }

    private func makeConnection(
        resolving resolved: (host: String, port: Int)? = nil,
        onResolve: (@Sendable (String) -> Void)? = nil
    ) -> KilnConnection {
        KilnConnection(defaults: defaults, rediscover: { name in
            onResolve?(name)
            return resolved
        })
    }

    // MARK: - Restoring

    func testDefaultsToPortEightyWithNothingSaved() {
        let connection = makeConnection()
        XCTAssertEqual(connection.host, "")
        XCTAssertEqual(connection.port, 80)
        XCTAssertNil(connection.serviceName)
    }

    func testRestoresSavedAddressAndServiceName() {
        defaults.set("127.0.0.1", forKey: UserDefaultsKeys.lastConnectedHost)
        defaults.set(8080, forKey: UserDefaultsKeys.kilnPort)
        defaults.set("Bisque Kiln Controller", forKey: UserDefaultsKeys.lastConnectedServiceName)

        let connection = makeConnection()
        XCTAssertEqual(connection.host, "127.0.0.1")
        XCTAssertEqual(connection.port, 8080)
        XCTAssertEqual(connection.serviceName, "Bisque Kiln Controller")
    }

    /// An install that predates service-name persistence has an address and no
    /// name. It must still restore, just without the re-resolve fallback.
    func testRestoresAnAddressSavedBeforeServiceNamesExisted() {
        defaults.set("127.0.0.1", forKey: UserDefaultsKeys.lastConnectedHost)
        defaults.set(80, forKey: UserDefaultsKeys.kilnPort)

        let connection = makeConnection()
        XCTAssertEqual(connection.host, "127.0.0.1")
        XCTAssertNil(connection.serviceName)
    }

    // MARK: - Re-resolving a stale address

    /// Both addresses are closed loopback ports so each attempt is refused
    /// immediately; an unbound address would sit out the client's 10s deadline
    /// and make this the slowest test in the suite for no extra coverage.
    func testUnreachableKilnWithAServiceNameAdoptsItsNewAddress() async {
        let connection = makeConnection(resolving: (host: "localhost", port: 59_999))
        connection.host = "127.0.0.1"  // the address the old lease had
        connection.port = 59_999
        connection.serviceName = "Bisque Kiln Controller"

        await connection.connect()

        XCTAssertEqual(
            connection.host, "localhost",
            "a kiln that moved should be followed, not reported as missing")
    }

    /// Nothing to resolve against, so the address must be left exactly as the
    /// user typed it — silently rewriting it would be worse than failing.
    func testUnreachableKilnWithoutAServiceNameKeepsItsAddress() async {
        var resolveCalls = 0
        let connection = KilnConnection(defaults: defaults, rediscover: { _ in
            resolveCalls += 1
            return (host: "localhost", port: 59_999)
        })
        connection.host = "127.0.0.1"
        connection.port = 59_999
        connection.serviceName = nil

        await connection.connect()

        XCTAssertEqual(connection.host, "127.0.0.1")
        XCTAssertEqual(resolveCalls, 0)
    }

    /// The service is on the network at the same address, so it is not a stale
    /// lease — it is a kiln that is not answering. One failure, not two.
    func testKilnThatResolvesToTheSameAddressIsNotRetried() async {
        let connection = makeConnection(resolving: (host: "127.0.0.1", port: 59_999))
        connection.host = "127.0.0.1"
        connection.port = 59_999
        connection.serviceName = "Bisque Kiln Controller"

        await connection.connect()

        XCTAssertEqual(connection.host, "127.0.0.1")
        if case .error = connection.connectionState {} else {
            XCTFail("expected an error state, got \(connection.connectionState)")
        }
    }

    func testKilnThatIsNoLongerOnTheNetworkKeepsItsLastKnownAddress() async {
        let connection = makeConnection(resolving: nil)
        connection.host = "127.0.0.1"
        connection.port = 59_999
        connection.serviceName = "Bisque Kiln Controller"

        await connection.connect()

        XCTAssertEqual(connection.host, "127.0.0.1")
    }

    func testAPortChangeAloneCountsAsMoved() async {
        let connection = makeConnection(resolving: (host: "127.0.0.1", port: 59_998))
        connection.host = "127.0.0.1"
        connection.port = 59_999
        connection.serviceName = "Bisque Kiln Controller"

        await connection.connect()

        XCTAssertEqual(connection.port, 59_998)
    }

    func testEmptyHostFailsBeforeAnyResolve() async {
        var resolveCalls = 0
        let connection = KilnConnection(defaults: defaults, rediscover: { _ in
            resolveCalls += 1
            return nil
        })
        connection.host = ""

        await connection.connect()

        XCTAssertEqual(resolveCalls, 0)
        XCTAssertEqual(connection.connectionState, .error("Enter the kiln's address"))
    }
    // MARK: - Concurrency around the fallback

    /// The lookup can take seconds. ConnectionView re-enables Connect and every
    /// discovered-kiln row the moment the state leaves `.connecting`, so
    /// leaving it early invites a second attempt to race this one.
    func testStateStaysConnectingWhileTheFallbackRuns() async {
        let entered = Gate()
        let release = Gate()
        let connection = KilnConnection(defaults: defaults, rediscover: { _ in
            entered.open()
            await release.wait()
            return (host: "localhost", port: 59_999)
        })
        connection.host = "127.0.0.1"
        connection.port = 59_999
        connection.serviceName = "Bisque Kiln Controller"

        let attempt = Task { await connection.connect() }
        await entered.wait()

        XCTAssertEqual(connection.connectionState, .connecting)

        release.open()
        await attempt.value
    }

    /// A superseded attempt must not write its own service's answer over the
    /// address the user has since chosen.
    func testAnAttemptSupersededDuringLookupDoesNotWriteBack() async {
        let entered = Gate()
        let release = Gate()
        let connection = KilnConnection(defaults: defaults, rediscover: { _ in
            entered.open()
            await release.wait()
            return (host: "stale-resolution.invalid", port: 1)
        })
        connection.host = "127.0.0.1"
        connection.port = 59_999
        connection.serviceName = "Bisque Kiln Controller"

        let first = Task { await connection.connect() }
        await entered.wait()

        // The user picks a different kiln while the first lookup is in flight.
        connection.host = "localhost"
        connection.port = 59_998
        connection.serviceName = nil
        await connection.connect()

        release.open()
        await first.value

        XCTAssertEqual(
            connection.host, "localhost",
            "the superseded attempt resumed and overwrote the user's choice")
    }
}

/// One-shot latch for coordinating with an injected async closure.
@MainActor
private final class Gate {
    private var waiters: [CheckedContinuation<Void, Never>] = []
    private var isOpen = false

    func open() {
        guard !isOpen else { return }
        isOpen = true
        let resuming = waiters
        waiters.removeAll()
        resuming.forEach { $0.resume() }
    }

    func wait() async {
        guard !isOpen else { return }
        await withCheckedContinuation { waiters.append($0) }
    }
}
