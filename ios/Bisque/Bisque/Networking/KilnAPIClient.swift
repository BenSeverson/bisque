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

struct OtaCheckResponse: Codable, Sendable {
    let current: String
    let latest: String
    let updateAvailable: Bool
    let url: String
    let sha256: String
    let size: Int
    let notes: String
}

struct OtaInstallResponse: Codable {
    let ok: Bool
    let version: String
    let message: String
}

actor KilnAPIClient {
    private let baseURL: URL
    private let session: URLSession
    private let otaSession: URLSession
    private var apiToken: String?

    /// Escapes a value being spliced into a URL *path*.
    ///
    /// Profile ids are normally client-generated UUIDs, but `importProfile`
    /// accepts arbitrary JSON, so an id could carry `/`, `..`, `?` or a space.
    /// Interpolated raw, `"x/../settings"` turns a profile delete into a
    /// request against a different endpoint, and a space makes
    /// `URL(string:)` return nil (#152). `.urlPathAllowed` still permits `/`,
    /// so slashes are escaped explicitly afterwards.
    static func pathComponent(_ raw: String) -> String {
        let encoded = raw.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? ""
        return encoded.replacingOccurrences(of: "/", with: "%2F")
    }

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

        /// OTA gets its own session because the timeouts above are wrong for it
        /// by an order of magnitude (#142).
        ///
        /// A 1.5–2 MB image is accepted only as fast as the ESP32 can erase and
        /// write flash, which routinely exceeds 30s — and `installOTA` returns
        /// only after the device has pulled the image from GitHub. Under the
        /// shared session URLSession cancelled the task at the resource
        /// deadline, mid-transfer, leaving a partial OTA write and showing a
        /// generic timeout.
        ///
        /// Keeping two sessions rather than relaxing the shared one preserves
        /// the short deadlines where they belong: a control request that has not
        /// answered in 10s should fail fast, not hang for ten minutes.
        let otaConfig = URLSessionConfiguration.default
        otaConfig.timeoutIntervalForRequest = 120
        otaConfig.timeoutIntervalForResource = 600
        self.otaSession = URLSession(configuration: otaConfig)
    }

    func setToken(_ token: String?) {
        self.apiToken = token
    }

    // MARK: - Generic Request

    /// `session:` overrides the short-deadline default for the one endpoint that
    /// legitimately takes minutes — see `otaSession` (#142).
    private func request<T: Decodable>(
        method: String = "GET",
        path: String,
        body: (any Encodable)? = nil,
        session overrideSession: URLSession? = nil
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
            (data, response) = try await (overrideSession ?? session).data(for: request)
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

    func saveProfile(_ profile: FiringProfile) async throws -> OkIdResponse {
        try await request(method: "POST", path: "/profiles", body: profile)
    }

    func deleteProfile(id: String) async throws -> OkResponse {
        try await request(method: "DELETE", path: "/profiles/\(Self.pathComponent(id))")
    }

    func importProfile(_ profile: FiringProfile) async throws -> OkIdResponse {
        try await request(method: "POST", path: "/profiles/import", body: profile)
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

    /// Uploads an already-read firmware image.
    ///
    /// Takes `Data` rather than a `URL` on purpose (#141). A file picked from
    /// iCloud Drive or Files is reachable only while its security-scoped
    /// resource is open, and that scope belongs to the picker callback — it
    /// cannot survive being handed to a detached upload task. Reading the bytes
    /// while the scope is held, then passing them here, makes the lifetime
    /// impossible to get wrong rather than merely correct today.
    func uploadOTA(firmware: Data, onProgress: @Sendable @escaping (Double) -> Void) async throws -> OkResponse {
        guard let url = URL(string: baseURL.absoluteString + "/ota") else {
            throw APIError.invalidURL
        }

        let fileData = firmware

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")

        if let token = apiToken, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let delegate = UploadProgressDelegate(onProgress: onProgress)
        let (data, response) = try await otaSession.upload(for: request, from: fileData, delegate: delegate)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Upload failed"
            throw APIError.serverError(statusCode: (response as? HTTPURLResponse)?.statusCode ?? 0, message: message)
        }

        return try JSONDecoder().decode(OkResponse.self, from: data)
    }

    func checkOTA() async throws -> OtaCheckResponse {
        try await request(method: "POST", path: "/ota/check")
    }

    /// Uses the OTA session: this returns only once the device has pulled the
    /// image from GitHub, which outlives the shared session's 30s resource
    /// deadline (#142).
    func installOTA() async throws -> OtaInstallResponse {
        try await request(method: "POST", path: "/ota/install", session: otaSession)
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
        // totalBytesExpectedToSend is 0 or NSURLSessionTransferSizeUnknown (-1)
        // when the length isn't known up front, which made this report NaN or a
        // negative percentage straight into the progress UI (#155).
        guard totalBytesExpectedToSend > 0 else { return }
        let fraction = Double(totalBytesSent) / Double(totalBytesExpectedToSend)
        onProgress(min(max(fraction, 0), 1) * 100)
    }
}
