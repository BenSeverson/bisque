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
    /// Looks a Bonjour instance up again. Injected so tests can drive the
    /// stale-address path without a kiln on the network.
    private let resolveService: (String) async -> (host: String, port: Int)?

    /// Set when the last attempt failed at the transport layer against a host
    /// the local-network permission governs, so the UI can offer the Settings
    /// toggle (#148). iOS has no API for reading that permission, so this is a
    /// suggestion of something to check, never a diagnosis.
    private(set) var suggestsLocalNetworkPermission = false

    init(
        defaults: UserDefaults = .standard,
        resolveService: @escaping (String) async -> (host: String, port: Int)? = {
            await KilnDiscovery.resolveService(named: $0)
        }
    ) {
        self.defaults = defaults
        self.resolveService = resolveService

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

    private enum Attempt {
        case connected
        /// Nothing answered — wrong address, kiln asleep, or permission denied.
        case unreachable
        /// Something answered and said no. Whatever it is, it is *there*.
        case refused
    }

    func connect() async {
        guard !host.isEmpty else {
            connectionState = .error("Enter the kiln's address")
            return
        }

        connectionState = .connecting
        suggestsLocalNetworkPermission = false

        guard case .unreachable = await attemptConnection() else { return }

        // A saved address is only as durable as the DHCP lease behind it, so a
        // kiln that has simply moved looks identical to one that is switched
        // off. The Bonjour instance name outlives the lease: if the service is
        // still on the network, its current address is authoritative and worth
        // one more attempt (#153).
        //
        // Only after an unreachable — a 401 means we found the kiln and it
        // wants a token, which re-resolving cannot help with — and only when
        // the address actually moved, so an off kiln fails once, not twice.
        guard let serviceName, !serviceName.isEmpty,
              let moved = await resolveService(serviceName),
              moved.host != host || moved.port != port
        else { return }

        host = moved.host
        port = moved.port
        connectionState = .connecting
        _ = await attemptConnection()
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
                connectionState = .error("Authentication required. Set API token.")
                return .refused
            case .connectionFailed:
                reportUnreachable()
                return .unreachable
            default:
                connectionState = .error(error.localizedDescription)
                return .refused
            }
        } catch {
            reportUnreachable()
            return .unreachable
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
