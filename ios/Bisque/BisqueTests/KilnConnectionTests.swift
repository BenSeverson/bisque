import XCTest

@testable import Bisque

/// Covers what `KilnConnection` remembers between launches, and what it does
/// about a remembered address that has gone stale (#153).
///
/// No `setUp`/`tearDown` overrides on purpose. They are declared nonisolated in
/// the Xcode 16 XCTest and `@MainActor` in the Xcode 26 one, so an override
/// that touches this class's actor-isolated state compiles on a current Mac and
/// fails on CI. Each test takes its own defaults from `makeDefaults()` instead,
/// which needs no override at all.
@MainActor
final class KilnConnectionTests: XCTestCase {
    /// A suite of its own, wiped on the way *in* rather than the way out — the
    /// next test gets a clean slate whether or not the last one finished, and
    /// nothing has to run after a failure to make that true.
    private static let suiteName = "com.bisque.KilnConnectionTests"

    private func makeDefaults() -> UserDefaults {
        let defaults = UserDefaults(suiteName: Self.suiteName)!
        defaults.removePersistentDomain(forName: Self.suiteName)
        return defaults
    }

    private func makeConnection(
        defaults: UserDefaults,
        resolving resolved: (host: String, port: Int)? = nil
    ) -> KilnConnection {
        KilnConnection(defaults: defaults, rediscover: { _ in resolved })
    }

    // MARK: - Restoring

    func testDefaultsToPortEightyWithNothingSaved() {
        let connection = makeConnection(defaults: makeDefaults())
        XCTAssertEqual(connection.host, "")
        XCTAssertEqual(connection.port, 80)
        XCTAssertNil(connection.serviceName)
    }

    func testRestoresSavedAddressAndServiceName() {
        let defaults = makeDefaults()
        defaults.set("127.0.0.1", forKey: UserDefaultsKeys.lastConnectedHost)
        defaults.set(8080, forKey: UserDefaultsKeys.kilnPort)
        defaults.set("Bisque Kiln Controller", forKey: UserDefaultsKeys.lastConnectedServiceName)

        let connection = makeConnection(defaults: defaults)
        XCTAssertEqual(connection.host, "127.0.0.1")
        XCTAssertEqual(connection.port, 8080)
        XCTAssertEqual(connection.serviceName, "Bisque Kiln Controller")
    }

    /// An install that predates service-name persistence has an address and no
    /// name. It must still restore, just without the re-resolve fallback.
    func testRestoresAnAddressSavedBeforeServiceNamesExisted() {
        let defaults = makeDefaults()
        defaults.set("127.0.0.1", forKey: UserDefaultsKeys.lastConnectedHost)
        defaults.set(80, forKey: UserDefaultsKeys.kilnPort)

        let connection = makeConnection(defaults: defaults)
        XCTAssertEqual(connection.host, "127.0.0.1")
        XCTAssertNil(connection.serviceName)
    }

    // MARK: - Re-resolving a stale address

    /// Every address here is a closed loopback port, refused instantly. An
    /// unbound address would instead sit out `KilnAPIClient`'s 10s deadline and
    /// make this the slowest test in the suite for no extra coverage.
    func testUnreachableKilnWithAServiceNameAdoptsItsNewAddress() async {
        let connection = makeConnection(
            defaults: makeDefaults(), resolving: (host: "localhost", port: 59_999))
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
        let calls = CallCounter()
        let connection = KilnConnection(defaults: makeDefaults()) { _ in
            calls.record()
            return (host: "localhost", port: 59_999)
        }
        connection.host = "127.0.0.1"
        connection.port = 59_999
        connection.serviceName = nil

        await connection.connect()

        XCTAssertEqual(connection.host, "127.0.0.1")
        XCTAssertEqual(calls.count, 0)
    }

    /// The service is on the network at the same address, so it is not a stale
    /// lease — it is a kiln that is not answering. One failure, not two.
    func testKilnThatResolvesToTheSameAddressIsNotRetried() async {
        let connection = makeConnection(
            defaults: makeDefaults(), resolving: (host: "127.0.0.1", port: 59_999))
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
        let connection = makeConnection(defaults: makeDefaults(), resolving: nil)
        connection.host = "127.0.0.1"
        connection.port = 59_999
        connection.serviceName = "Bisque Kiln Controller"

        await connection.connect()

        XCTAssertEqual(connection.host, "127.0.0.1")
    }

    func testAPortChangeAloneCountsAsMoved() async {
        let connection = makeConnection(
            defaults: makeDefaults(), resolving: (host: "127.0.0.1", port: 59_998))
        connection.host = "127.0.0.1"
        connection.port = 59_999
        connection.serviceName = "Bisque Kiln Controller"

        await connection.connect()

        XCTAssertEqual(connection.port, 59_998)
    }

    func testEmptyHostFailsBeforeAnyResolve() async {
        let calls = CallCounter()
        let connection = KilnConnection(defaults: makeDefaults()) { _ in
            calls.record()
            return nil
        }
        connection.host = ""

        await connection.connect()

        XCTAssertEqual(calls.count, 0)
        XCTAssertEqual(connection.connectionState, .error("Enter the kiln's address"))
    }

    // MARK: - Concurrency around the fallback

    /// The lookup can take seconds. ConnectionView re-enables Connect and every
    /// discovered-kiln row the moment the state leaves `.connecting`, so
    /// leaving it early invites a second attempt to race this one.
    func testStateStaysConnectingWhileTheFallbackRuns() async {
        let entered = Gate()
        let release = Gate()
        let connection = KilnConnection(defaults: makeDefaults()) { _ in
            entered.open()
            await release.wait()
            return (host: "localhost", port: 59_999)
        }
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
        let connection = KilnConnection(defaults: makeDefaults()) { _ in
            entered.open()
            await release.wait()
            return (host: "stale-resolution.invalid", port: 1)
        }
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

/// Counts calls to an injected closure. A plain `var` captured by the closure
/// would be a mutable capture crossing into an escaping context.
@MainActor
private final class CallCounter {
    private(set) var count = 0
    func record() { count += 1 }
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
