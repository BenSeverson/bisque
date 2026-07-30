import Foundation
import Combine

@MainActor @Observable
final class KilnWebSocketManager {
    private(set) var isConnected = false
    private(set) var lastUpdate: TempUpdateData?

    private var webSocketTask: URLSessionWebSocketTask?
    private let session = URLSession(configuration: .default)
    private var url: URL?
    private var apiToken: String?
    private var reconnectDelay: TimeInterval = 1
    private var reconnectTask: Task<Void, Never>?
    private var receiveTask: Task<Void, Never>?
    private var shouldReconnect = false

    /// Bumped by every `openConnection()`. A receive loop carries the value it
    /// was started with and stays silent once it no longer matches.
    ///
    /// Without it, a loop whose socket has been replaced still reaches its catch
    /// block and schedules a reconnect — and that reconnect cancels the *live*
    /// socket, whose loop then schedules the next one. Self-sustaining churn at
    /// 1–8s intervals, losing updates the whole time. Cancelling the task is not
    /// enough on its own: `Task.isCancelled` guards loop entry, not the catch,
    /// and `openConnection()` can supersede a loop that was never cancelled.
    private var generation = 0

    let updateSubject = PassthroughSubject<TempUpdateData, Never>()
    let otaSubject = PassthroughSubject<OTAEvent, Never>()

    /// - Parameter apiToken: credential for the handshake. The firmware gates
    ///   `/api/v1/ws` with the same check as the REST API, so without this a
    ///   token-protected kiln rejects the upgrade with 401 and the app silently
    ///   falls back to polling.
    func connect(host: String, port: Int = 80, apiToken: String? = nil) {
        guard let url = URL(string: "ws://\(host):\(port)/api/v1/ws") else { return }
        self.url = url
        self.apiToken = apiToken
        self.shouldReconnect = true
        self.reconnectDelay = 1
        openConnection()
    }

    func disconnect() {
        // Bumped here too, so a loop cancelled by an explicit disconnect is
        // silenced by generation alone rather than relying on shouldReconnect —
        // which connect() may already have set back to true.
        generation += 1
        shouldReconnect = false
        reconnectTask?.cancel()
        reconnectTask = nil
        receiveTask?.cancel()
        receiveTask = nil
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        isConnected = false
    }

    private func openConnection() {
        guard let url = url else { return }

        generation += 1
        let thisGeneration = generation

        // Supersede any loop still running against the outgoing socket, so it
        // cannot outlive this call and report the socket it owned as lost.
        receiveTask?.cancel()
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        // Via URLRequest, not the bare URL, so the handshake can carry the
        // Authorization header. URLSession permits this on a WebSocket where
        // the browser WebSocket API does not — which is why the web client has
        // to use `?token=` for the same endpoint.
        var request = URLRequest(url: url)
        if let token = apiToken, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let task = session.webSocketTask(with: request)
        self.webSocketTask = task
        task.resume()

        isConnected = true
        reconnectDelay = 1

        receiveTask = Task { [weak self] in
            await self?.receiveLoop(task: task, myGeneration: thisGeneration)
        }
    }

    nonisolated private func receiveLoop(task: URLSessionWebSocketTask, myGeneration: Int) async {
        while !Task.isCancelled {
            do {
                let message = try await task.receive()
                let raw: Data? = switch message {
                case .string(let text): text.data(using: .utf8)
                case .data(let data): data
                @unknown default: nil
                }
                guard let raw,
                      let envelope = try? JSONDecoder().decode(WSTypeEnvelope.self, from: raw) else {
                    continue
                }

                switch envelope.type {
                case "temp_update":
                    if let msg = try? JSONDecoder().decode(WebSocketMessage.self, from: raw) {
                        await MainActor.run { [weak self] in
                            self?.lastUpdate = msg.data
                            self?.updateSubject.send(msg.data)
                        }
                    }
                case "ota_progress", "ota_complete", "ota_error":
                    if let ota = try? JSONDecoder().decode(OTAWebSocketMessage.self, from: raw),
                       let event = ota.event {
                        await MainActor.run { [weak self] in
                            self?.otaSubject.send(event)
                        }
                    }
                default:
                    break
                }
            } catch {
                await MainActor.run { [weak self] in
                    guard let self, myGeneration == self.generation else {
                        // This socket was replaced deliberately — by disconnect()
                        // or by a newer openConnection(). Its failure is expected
                        // and says nothing about the connection that is live now.
                        return
                    }
                    self.isConnected = false
                    self.scheduleReconnect()
                }
                return
            }
        }
    }

    private func scheduleReconnect() {
        guard shouldReconnect else { return }
        let delay = reconnectDelay
        reconnectDelay = min(reconnectDelay * 2, 8)

        reconnectTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled else { return }
            self?.openConnection()
        }
    }
}
