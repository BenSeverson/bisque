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
            connectionState = .error("Enter a kiln IP address")
            return
        }

        connectionState = .connecting

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
            default:
                connectionState = .error(error.localizedDescription)
            }
        } catch {
            connectionState = .error("Cannot reach kiln at \(host)")
        }
    }

    func disconnect() {
        webSocket.disconnect()
        apiClient = nil
        connectionState = .disconnected
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
