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
                let update: TempUpdateData? = switch message {
                case .string(let text):
                    text.data(using: .utf8).flatMap { try? JSONDecoder().decode(WebSocketMessage.self, from: $0) }
                        .flatMap { $0.type == "temp_update" ? $0.data : nil }
                case .data(let data):
                    (try? JSONDecoder().decode(WebSocketMessage.self, from: data))
                        .flatMap { $0.type == "temp_update" ? $0.data : nil }
                @unknown default:
                    nil
                }

                if let update {
                    await MainActor.run { [weak self] in
                        self?.lastUpdate = update
                        self?.updateSubject.send(update)
                    }
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
