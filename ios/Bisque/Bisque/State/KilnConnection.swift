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

    private(set) var apiClient: KilnAPIClient?
    let webSocket = KilnWebSocketManager()

    /// Set when the last attempt failed at the transport layer against a host
    /// the local-network permission governs, so the UI can offer the Settings
    /// toggle (#148). iOS has no API for reading that permission, so this is a
    /// suggestion of something to check, never a diagnosis.
    private(set) var suggestsLocalNetworkPermission = false

    init() {
        // Restore last connection
        if let savedHost = UserDefaults.standard.string(forKey: UserDefaultsKeys.lastConnectedHost) {
            host = savedHost
        }
        port = UserDefaults.standard.integer(forKey: UserDefaultsKeys.kilnPort)
        if port == 0 { port = 80 }

        // Restore API token from Keychain
        apiToken = KeychainHelper.load(key: "apiToken")
    }

    func connect() async {
        guard !host.isEmpty else {
            connectionState = .error("Enter the kiln's address")
            return
        }

        connectionState = .connecting
        suggestsLocalNetworkPermission = false

        do {
            let client = try KilnAPIClient(host: host, port: port, apiToken: apiToken)
            // Test connection with a status request
            _ = try await client.getStatus()

            self.apiClient = client
            self.connectionState = .connected

            // Start WebSocket
            webSocket.connect(host: host, port: port, apiToken: apiToken)

            // Save connection
            UserDefaults.standard.set(host, forKey: UserDefaultsKeys.lastConnectedHost)
            UserDefaults.standard.set(port, forKey: UserDefaultsKeys.kilnPort)
        } catch let error as APIError {
            switch error {
            case .unauthorized:
                connectionState = .error("Authentication required. Set API token.")
            case .connectionFailed:
                reportUnreachable()
            default:
                connectionState = .error(error.localizedDescription)
            }
        } catch {
            reportUnreachable()
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
