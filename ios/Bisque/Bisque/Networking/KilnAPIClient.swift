import Foundation

struct OkResponse: Codable {
    let ok: Bool
}

struct OkIdResponse: Codable {
    let ok: Bool
    let id: String
}

struct PauseResponse: Codable {
    let ok: Bool
    let action: String
}

struct RelayTestResponse: Codable {
    let ok: Bool
    let durationSeconds: Int
}

struct ConeFireRequest: Codable {
    let coneId: Int
    let speed: Int          // 0=slow, 1=medium, 2=fast
    let preheat: Bool
    let slowCool: Bool
    let save: Bool
}

struct StartFiringRequest: Codable {
    let profileId: String
    let delayMinutes: Int
}

struct AutotuneStartRequest: Codable {
    let setpoint: Double
    let hysteresis: Double
}

struct RelayTestRequest: Codable {
    let durationSeconds: Int
}

actor KilnAPIClient {
    private let baseURL: URL
    private let session: URLSession
    private var apiToken: String?

    init(host: String, port: Int = 80, apiToken: String? = nil) throws {
        guard let url = URL(string: "http://\(host):\(port)/api/v1") else {
            throw APIError.invalidURL
        }
        self.baseURL = url
        self.apiToken = apiToken

        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 10
        config.timeoutIntervalForResource = 30
        self.session = URLSession(configuration: config)
    }

    func setToken(_ token: String?) {
        self.apiToken = token
    }

    // MARK: - Generic Request

    private func request<T: Decodable>(
        method: String = "GET",
        path: String,
        body: (any Encodable)? = nil
    ) async throws -> T {
        guard let url = URL(string: baseURL.absoluteString + path) else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token = apiToken, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        if let body = body {
            request.httpBody = try JSONEncoder().encode(body)
        }

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await session.data(for: request)
        } catch is URLError {
            throw APIError.connectionFailed
        }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.connectionFailed
        }

        if httpResponse.statusCode == 401 {
            throw APIError.unauthorized
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.serverError(statusCode: httpResponse.statusCode, message: message)
        }

        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw APIError.decodingError(error)
        }
    }

    private func requestText(method: String = "GET", path: String) async throws -> String {
        guard let url = URL(string: baseURL.absoluteString + path) else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = method

        if let token = apiToken, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await session.data(for: request)
        } catch is URLError {
            throw APIError.connectionFailed
        }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.connectionFailed
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.serverError(statusCode: httpResponse.statusCode, message: message)
        }

        return String(data: data, encoding: .utf8) ?? ""
    }

    // MARK: - Status

    func getStatus() async throws -> StatusResponse {
        try await request(path: "/status")
    }

    // MARK: - Profiles

    func getProfiles() async throws -> [FiringProfile] {
        try await request(path: "/profiles")
    }

    func getProfile(id: String) async throws -> FiringProfile {
        try await request(path: "/profiles/\(id)")
    }

    func saveProfile(_ profile: FiringProfile) async throws -> OkIdResponse {
        try await request(method: "POST", path: "/profiles", body: profile)
    }

    func deleteProfile(id: String) async throws -> OkResponse {
        try await request(method: "DELETE", path: "/profiles/\(id)")
    }

    func importProfile(_ profile: FiringProfile) async throws -> OkIdResponse {
        try await request(method: "POST", path: "/profiles/import", body: profile)
    }

    func exportProfileURL(id: String) -> URL? {
        URL(string: baseURL.absoluteString + "/profiles/\(id)/export")
    }

    // MARK: - Cone Fire

    func getConeTable() async throws -> [ConeEntry] {
        try await request(path: "/cone-table")
    }

    func generateConeFire(_ params: ConeFireRequest) async throws -> FiringProfile {
        try await request(method: "POST", path: "/profiles/cone-fire", body: params)
    }

    // MARK: - Firing Control

    func startFiring(profileId: String, delayMinutes: Int = 0) async throws -> OkResponse {
        try await request(method: "POST", path: "/firing/start",
                         body: StartFiringRequest(profileId: profileId, delayMinutes: delayMinutes))
    }

    func stopFiring() async throws -> OkResponse {
        try await request(method: "POST", path: "/firing/stop")
    }

    func pauseFiring() async throws -> PauseResponse {
        try await request(method: "POST", path: "/firing/pause")
    }

    func skipSegment() async throws -> OkResponse {
        try await request(method: "POST", path: "/firing/skip-segment")
    }

    // MARK: - Settings

    func getSettings() async throws -> KilnSettings {
        try await request(path: "/settings")
    }

    func saveSettings(_ settings: KilnSettings) async throws -> OkResponse {
        try await request(method: "POST", path: "/settings", body: settings)
    }

    // MARK: - System

    func getSystemInfo() async throws -> SystemInfo {
        try await request(path: "/system")
    }

    // MARK: - Auto-tune

    func startAutotune(setpoint: Double, hysteresis: Double = 5) async throws -> OkResponse {
        try await request(method: "POST", path: "/autotune/start",
                         body: AutotuneStartRequest(setpoint: setpoint, hysteresis: hysteresis))
    }

    func stopAutotune() async throws -> OkResponse {
        try await request(method: "POST", path: "/autotune/stop")
    }

    func getAutotuneStatus() async throws -> AutotuneStatus {
        try await request(path: "/autotune/status")
    }

    // MARK: - History

    func getHistory() async throws -> [HistoryRecord] {
        try await request(path: "/history")
    }

    func getHistoryTrace(recordId: Int) async throws -> String {
        try await requestText(path: "/history/\(recordId)/trace")
    }

    // MARK: - OTA

    func uploadOTA(fileURL: URL, onProgress: @Sendable @escaping (Double) -> Void) async throws -> OkResponse {
        guard let url = URL(string: baseURL.absoluteString + "/ota") else {
            throw APIError.invalidURL
        }

        let fileData = try Data(contentsOf: fileURL)

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")

        if let token = apiToken, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let delegate = UploadProgressDelegate(onProgress: onProgress)
        let (data, response) = try await session.upload(for: request, from: fileData, delegate: delegate)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Upload failed"
            throw APIError.serverError(statusCode: (response as? HTTPURLResponse)?.statusCode ?? 0, message: message)
        }

        return try JSONDecoder().decode(OkResponse.self, from: data)
    }

    // MARK: - Diagnostics

    func testRelay(durationSeconds: Int = 2) async throws -> RelayTestResponse {
        try await request(method: "POST", path: "/diagnostics/relay",
                         body: RelayTestRequest(durationSeconds: durationSeconds))
    }

    func getThermocoupleDiag() async throws -> DiagThermocouple {
        try await request(path: "/diagnostics/thermocouple")
    }
}

// MARK: - Upload Progress Delegate

final class UploadProgressDelegate: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    private let onProgress: @Sendable (Double) -> Void

    init(onProgress: @Sendable @escaping (Double) -> Void) {
        self.onProgress = onProgress
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    didSendBodyData bytesSent: Int64, totalBytesSent: Int64,
                    totalBytesExpectedToSend: Int64) {
        let progress = Double(totalBytesSent) / Double(totalBytesExpectedToSend)
        onProgress(progress * 100)
    }
}
