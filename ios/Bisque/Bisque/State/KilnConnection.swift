import SwiftUI
import Combine

enum ConnectionState: Equatable {
    case disconnected
    case connecting
    case connected
    case error(String)

    var isConnected: Bool {
        if case .connected = self { return true }
        return false
    }
}

@MainActor @Observable
final class KilnConnection {
    var host: String = ""
    var port: Int = 80
    var connectionState: ConnectionState = .disconnected
    var apiToken: String? = nil

    /// The Bonjour instance the current address came from, or nil when the
    /// user typed an address by hand. A hand-typed host is not tied to a
    /// service, so there is nothing to re-resolve it against.
    var serviceName: String?

    private(set) var apiClient: KilnAPIClient?
    let webSocket = KilnWebSocketManager()

    private let defaults: UserDefaults

    /// Finds where a known Bonjour instance lives now, and confirms the thing
    /// answering there is a kiln before handing the address back.
    ///
    /// The confirmation is not optional. Anything on the LAN can advertise the
    /// saved instance name, and the retry connects with the API token attached
    /// — so without an anonymous check first, an unreachable kiln is all it
    /// takes to walk a kiln-controlling credential into a stranger's service.
    /// `KilnDiscovery.verify` already establishes identity before presenting
    /// any credential (#268), so the default composes with it rather than
    /// reimplementing the rule.
    ///
    /// What it cannot check is *which* kiln answered. Every controller
    /// hardcodes the same mDNS hostname and instance name and publishes no TXT
    /// record, and `/api/v1/system` carries nothing unique either, so no client
    /// can currently tell two units apart — a saved bare address has the same
    /// weakness. Issue #274 tracks giving the firmware a per-device id to
    /// verify here.
    ///
    /// Injected so tests can drive the stale-address path without a kiln on the
    /// network.
    private let rediscover: (String) async -> (host: String, port: Int)?

    /// Supersedes in-flight attempts. `connect()` awaits the network twice with
    /// a Bonjour resolve in between, and the UI can start another attempt
    /// during any of it; without this, the older task would resume afterwards
    /// and overwrite `host`/`port`/state with its own service's answer.
    private var attemptGeneration = 0

    /// Set when the last attempt failed at the transport layer against a host
    /// the local-network permission governs, so the UI can offer the Settings
    /// toggle (#148). iOS has no API for reading that permission, so this is a
    /// suggestion of something to check, never a diagnosis.
    private(set) var suggestsLocalNetworkPermission = false

    init(
        defaults: UserDefaults = .standard,
        rediscover: @escaping (String) async -> (host: String, port: Int)? = {
            serviceName in
            guard let moved = await KilnDiscovery.resolveService(named: serviceName),
                // apiToken: nil — this probe exists to establish identity, so it
                // must not carry a credential itself.
                await KilnDiscovery.verify(
                    host: moved.host, port: moved.port, serviceName: serviceName,
                    apiToken: nil, timeout: 4) != nil
            else { return nil }
            return moved
        }
    ) {
        self.defaults = defaults
        self.rediscover = rediscover

        // Restore last connection
        if let savedHost = defaults.string(forKey: UserDefaultsKeys.lastConnectedHost) {
            host = savedHost
        }
        port = defaults.integer(forKey: UserDefaultsKeys.kilnPort)
        if port == 0 { port = 80 }
        serviceName = defaults.string(forKey: UserDefaultsKeys.lastConnectedServiceName)

        // Restore API token from Keychain
        apiToken = KeychainHelper.load(key: "apiToken")
    }

    /// How an attempt failed, held until the caller decides it is final.
    ///
    /// Reporting it immediately would drop the state out of `.connecting` while
    /// the Bonjour fallback is still running, and the UI re-enables Connect and
    /// the discovered-kiln rows the moment that happens.
    private enum Failure {
        case unreachable
        case message(String)
    }

    private enum Attempt {
        case connected
        /// Our kiln is not at this address — nothing answered, or something
        /// answered that did not identify itself as the kiln. Worth looking up
        /// where it went.
        case notFound(Failure)
        /// Found, and it said no. A 401 is the kiln telling us it wants a
        /// token; no amount of re-resolving changes that.
        case refused(Failure)
    }

    func connect() async {
        guard !host.isEmpty else {
            connectionState = .error("Enter the kiln's address")
            return
        }

        attemptGeneration &+= 1
        let generation = attemptGeneration

        connectionState = .connecting
        suggestsLocalNetworkPermission = false

        let outcome = await attemptConnection()
        guard generation == attemptGeneration else { return }

        guard case .notFound(let failure) = outcome else {
            if case .refused(let failure) = outcome { report(failure) }
            return
        }

        // A saved address is only as durable as the DHCP lease behind it, so a
        // kiln that has simply moved looks identical to one that is switched
        // off — or, once the lease is handed to something else, to a stranger
        // answering on port 80. The Bonjour instance name outlives the lease:
        // if the service is still on the network, its current address is
        // authoritative and worth one more attempt (#153).
        //
        // The state stays `.connecting` across the lookup on purpose. Dropping
        // to `.error` here would re-enable every button in ConnectionView while
        // this is still running.
        guard let serviceName, !serviceName.isEmpty else {
            report(failure)
            return
        }

        let moved = await rediscover(serviceName)
        guard generation == attemptGeneration else { return }

        // Only when the address actually moved: a kiln that resolves to where
        // we just looked is off, not lost, and should fail once rather than
        // twice as slowly.
        guard let moved, moved.host != host || moved.port != port else {
            report(failure)
            return
        }

        host = moved.host
        port = moved.port

        let retry = await attemptConnection()
        guard generation == attemptGeneration else { return }
        switch retry {
        case .connected: break
        case .notFound(let failure), .refused(let failure): report(failure)
        }
    }

    private func report(_ failure: Failure) {
        switch failure {
        case .unreachable: reportUnreachable()
        case .message(let message): connectionState = .error(message)
        }
    }

    private func attemptConnection() async -> Attempt {
        do {
            let client = try KilnAPIClient(host: host, port: port, apiToken: apiToken)
            // Test connection with a status request
            _ = try await client.getStatus()

            self.apiClient = client
            self.connectionState = .connected

            // Start WebSocket
            webSocket.connect(host: host, port: port, apiToken: apiToken)

            // Save connection
            defaults.set(host, forKey: UserDefaultsKeys.lastConnectedHost)
            defaults.set(port, forKey: UserDefaultsKeys.kilnPort)
            // Persisted alongside the address, not instead of it: the address
            // is what the next launch dials, and the name is only the fallback
            // for when it has gone stale.
            if let serviceName, !serviceName.isEmpty {
                defaults.set(serviceName, forKey: UserDefaultsKeys.lastConnectedServiceName)
            } else {
                defaults.removeObject(forKey: UserDefaultsKeys.lastConnectedServiceName)
            }
            return .connected
        } catch let error as APIError {
            switch error {
            case .unauthorized:
                return .refused(.message("Authentication required. Set API token."))
            case .connectionFailed:
                return .notFound(.unreachable)
            default:
                // A non-2xx or an undecodable body is not our kiln answering.
                // The likeliest cause is exactly the case this fallback exists
                // for: DHCP handed the old address to some other device, which
                // is now answering on port 80. Treating that as "found" would
                // make a stale lease permanently unrecoverable whenever its new
                // owner happens to be reachable.
                return .notFound(.message(error.localizedDescription))
            }
        } catch {
            return .notFound(.unreachable)
        }
    }

    /// Reports an unreachable kiln, naming the local-network permission when
    /// the address is one that permission gates.
    ///
    /// A denial is indistinguishable from a wrong IP or a sleeping kiln at the
    /// URLSession layer — every one of them surfaces as a plain transport
    /// failure — so the wording offers the toggle as a candidate rather than
    /// asserting it. Before this, a first-launch "Don't Allow" left the app
    /// permanently unable to connect with nothing on screen tying the two
    /// together (#148).
    private func reportUnreachable() {
        suggestsLocalNetworkPermission = LocalNetwork.requiresPermission(host: host)
        connectionState = .error(
            suggestsLocalNetworkPermission
                ? """
                    Cannot reach kiln at \(host). Check that the kiln is powered on \
                    and on this Wi-Fi network, and that Local Network access is \
                    enabled for Bisque in Settings.
                    """
                : "Cannot reach kiln at \(host)")
    }

    func disconnect() {
        webSocket.disconnect()
        apiClient = nil
        connectionState = .disconnected
        suggestsLocalNetworkPermission = false
    }

    /// Re-establishes the live feed after the app has been suspended (#147).
    ///
    /// iOS tears the WebSocket down within seconds of backgrounding, and the app
    /// declares no background modes, so on return the socket is dead while
    /// `connectionState` still reads `.connected` and the UI presents whatever
    /// reading it had when the phone went in a pocket. Nothing noticed until the
    /// user pulled to refresh.
    ///
    /// Only meaningful when a connection was already established: a foreground
    /// event must not start dialling a kiln the user never connected to, or
    /// overwrite an `.error` they still need to read.
    func resumeIfConnected() {
        guard case .connected = connectionState, !host.isEmpty else { return }
        webSocket.disconnect()
        webSocket.connect(host: host, port: port, apiToken: apiToken)
    }

    /// Returns false if the token could not be persisted, so the caller can say
    /// so rather than letting the user discover it as a lockout on next launch
    /// (#151). The in-memory token is still adopted either way — the current
    /// session works; only persistence failed.
    @discardableResult
    func setAndSaveToken(_ token: String?) -> Bool {
        apiToken = token
        if let token = token, !token.isEmpty {
            return KeychainHelper.save(key: "apiToken", value: token)
        }
        KeychainHelper.delete(key: "apiToken")
        return true
    }

    func autoConnect() async {
        guard !host.isEmpty, !connectionState.isConnected else { return }
        await connect()
    }
}
