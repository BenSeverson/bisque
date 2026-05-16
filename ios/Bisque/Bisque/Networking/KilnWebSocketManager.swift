import Foundation
import Combine

@MainActor @Observable
final class KilnWebSocketManager {
    private(set) var isConnected = false
    private(set) var lastUpdate: TempUpdateData?

    private var webSocketTask: URLSessionWebSocketTask?
    private let session = URLSession(configuration: .default)
    private var url: URL?
    private var reconnectDelay: TimeInterval = 1
    private var reconnectTask: Task<Void, Never>?
    private var receiveTask: Task<Void, Never>?
    private var shouldReconnect = false

    let updateSubject = PassthroughSubject<TempUpdateData, Never>()
    let otaSubject = PassthroughSubject<OTAEvent, Never>()

    func connect(host: String, port: Int = 80) {
        guard let url = URL(string: "ws://\(host):\(port)/api/v1/ws") else { return }
        self.url = url
        self.shouldReconnect = true
        self.reconnectDelay = 1
        openConnection()
    }

    func disconnect() {
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

        webSocketTask?.cancel(with: .goingAway, reason: nil)
        let task = session.webSocketTask(with: url)
        self.webSocketTask = task
        task.resume()

        isConnected = true
        reconnectDelay = 1

        receiveTask = Task { [weak self] in
            await self?.receiveLoop(task: task)
        }
    }

    nonisolated private func receiveLoop(task: URLSessionWebSocketTask) async {
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
                    self?.isConnected = false
                    self?.scheduleReconnect()
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
