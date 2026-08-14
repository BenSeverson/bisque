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

struct OtaConfirmResponse: Codable, Sendable {
    let ok: Bool
    let message: String
}

/// GET /api/v1/ota/status — mirrors `build_ota_status_json` in api_json.c.
///
/// Almost every field is optional because each part comes from a separate
/// esp_ota lookup in the handler, and a failed lookup drops its key rather than
/// emitting a placeholder — `ota_status_minimal.json` is the whole response
/// reduced to `rollbackAvailable`, which is the one field always present.
struct OtaStatus: Codable, Sendable {
    /// The slot the controller booted from, with the build stamp of the image
    /// in it.
    struct RunningPartition: Codable, Sendable {
        let label: String
        let address: Int
        let size: Int
        /// Absent when `esp_ota_get_state_partition()` failed; `pendingVerify`
        /// on the parent is emitted with it and always agrees.
        let state: String?
        let version: String?
        let date: String?
        let time: String?
        let idfVersion: String?
    }

    /// The slot the *next* update would be written to — labelled and sized, but
    /// carrying no build stamp, since the firmware does not read one from it.
    struct UpdatePartition: Codable, Sendable {
        let label: String
        let size: Int
    }

    let running: RunningPartition?
    let nextUpdate: UpdatePartition?
    /// What the next reboot will run. Differs from `running?.label` only
    /// between a rollback request and the reboot that carries it out.
    let bootPartition: String?
    let pendingVerify: Bool?
    let rollbackAvailable: Bool
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

    /// `session:` overrides the short-deadline default for the OTA endpoints,
    /// which legitimately take minutes — see `otaSession` (#142).
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

    /// Also on the OTA session. `handle_ota_check` waits synchronously for
    /// `ota_check()` to fetch the release manifest from GitHub, bounded by
    /// CONFIG_OTA_HTTP_TIMEOUT_MS — 15s by default and settable to 120s. Under
    /// the shared session's 10s request deadline the app gave up before the
    /// controller answered, so Install never appeared even when an update was
    /// there (#142).
    func checkOTA() async throws -> OtaCheckResponse {
        try await request(method: "POST", path: "/ota/check", session: otaSession)
    }

    /// Uses the OTA session: this returns only once the device has pulled the
    /// image from GitHub, which outlives the shared session's 30s resource
    /// deadline (#142).
    func installOTA() async throws -> OtaInstallResponse {
        try await request(method: "POST", path: "/ota/install", session: otaSession)
    }

    /// Which image is running and whether the previous one can be booted again
    /// (#177). On the short-deadline session: it is a handful of partition
    /// lookups, with nothing to fetch from GitHub.
    func getOTAStatus() async throws -> OtaStatus {
        try await request(path: "/ota/status")
    }

    /// What a rollback request could be established about the controller.
    ///
    /// `acknowledged` is a reply that arrived; `unacknowledged` is a request
    /// that went out and got nothing back, which is what a reboot mid-reply
    /// looks like. The caller words its outcome from this instead of being
    /// handed a "success" the app cannot actually vouch for.
    enum RollbackOutcome: Sendable {
        case acknowledged
        case unacknowledged
    }

    /// Reverts to the previously-booted image (#177).
    ///
    /// Written out rather than going through `request()` because it returns
    /// nothing to decode and because the interesting case is a request that is
    /// never answered: `handle_ota_rollback` calls
    /// `esp_ota_mark_app_invalid_rollback_and_reboot()`, so the controller is
    /// gone before it can reply. Treating that as a failure would tell the user
    /// the rollback failed while the kiln was busy performing it.
    ///
    /// Not every transport error means that, though, and the two are worth
    /// separating: `cannotConnectToHost`, `cannotFindHost`, `dnsLookupFailed`,
    /// `notConnectedToInternet` and friends all fail *before* delivery — the
    /// kiln never saw the request and its firmware did not change — so they
    /// surface as errors.
    ///
    /// `timedOut` is the ambiguous one, and it cannot be settled by its code:
    /// it covers both a connection that never came up and a request that went
    /// out to a peer which then went silent — the latter being exactly how a
    /// rebooting ESP32 looks, since it tears the socket down without an RST.
    /// So delivery is *observed* rather than inferred: `RequestDeliveryProbe`
    /// reads `requestEndDate` off the task metrics, which is set only once the
    /// request has actually been written to the connection. No evidence of
    /// delivery, no claim that the rollback started.
    ///
    /// A real HTTP status means the device is very much still up and did not
    /// change its firmware — 400 with no image behind the running one, 409
    /// during a firing or an update, 401 unauthenticated — so those still throw.
    func rollbackOTA() async throws -> RollbackOutcome {
        guard let url = URL(string: baseURL.absoluteString + "/ota/rollback") else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        if let token = apiToken, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let probe = RequestDeliveryProbe()
        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await session.data(for: request, delegate: probe)
        } catch let error as URLError {
            guard Self.mayFollowDelivery(error.code, requestWasSent: probe.requestWasSent) else {
                throw APIError.connectionFailed
            }
            return .unacknowledged
        }

        /* An answer that is not an HTTP response is not one this can read a
           status from, but it did come back from somewhere — treat it like the
           truncated-reply case rather than inventing a server error. */
        guard let httpResponse = response as? HTTPURLResponse else {
            return .unacknowledged
        }

        if httpResponse.statusCode == 401 {
            throw APIError.unauthorized
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.serverError(statusCode: httpResponse.statusCode, message: message)
        }

        /* A 2xx alone does not identify the responder. A captive portal, a
           proxy, or whatever took the kiln's DHCP lease since the app last
           talked to it all answer with one, and "rolling back" is a claim worth
           more than a status code — so the body has to be the kiln's own. */
        guard let ack = try? JSONDecoder().decode(OkResponse.self, from: data), ack.ok else {
            throw APIError.serverError(
                statusCode: httpResponse.statusCode,
                message: "Reply did not come from the kiln; nothing was changed")
        }

        return .acknowledged
    }

    /// Whether a `URLError` could have happened *after* the request reached the
    /// kiln. Anything not listed here failed on the way out — name resolution,
    /// no route, no radio, connection refused — and proves the controller never
    /// received the POST.
    ///
    /// The first group can only arise while reading a reply, so delivery is
    /// implied by the error itself.
    ///
    /// The second group is ambiguous and is admitted only with proof of
    /// delivery. `timedOut` covers a deadline that expired during connection
    /// setup as well as one that expired waiting for an answer.
    /// `networkConnectionLost` looks like the reboot signature but is also what
    /// a reused pooled connection reports when the peer closed it before the
    /// request was written — and URLSession does not silently retry a POST, so
    /// that failure surfaces here having sent nothing.
    private static func mayFollowDelivery(_ code: URLError.Code, requestWasSent: Bool) -> Bool {
        switch code {
        case .cannotParseResponse, .zeroByteResource, .badServerResponse, .dataLengthExceedsMaximum:
            return true
        case .timedOut, .networkConnectionLost:
            return requestWasSent
        default:
            return false
        }
    }

    /// Marks the running image valid, cancelling the pending rollback (#177).
    /// `ota_confirm.c` normally does this on its own after a healthy-uptime
    /// window; this is the manual path for someone watching an update land.
    func confirmOTA() async throws -> OtaConfirmResponse {
        try await request(method: "POST", path: "/ota/confirm")
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

// MARK: - Request Delivery Probe

/// Refuses redirects, and records whether the request was actually written to
/// the connection (#177).
///
/// `URLSessionTaskMetrics` carries a `requestEndDate` per transaction, set when
/// the last byte of the request went out — so a non-nil one is proof the kiln
/// received the POST, which no `URLError.Code` can establish on its own. Used
/// by `rollbackOTA()` to tell "the kiln rebooted before replying" apart from
/// "the connection never came up", which URLSession reports identically as
/// `.timedOut`.
///
/// Metrics are delivered before the task's completion resumes the awaiting
/// call, so the flag is set by the time it is read. If they never arrive, this
/// stays false and the caller reports a failure rather than claiming a rollback
/// it cannot evidence — the safe direction for a destructive operation.
final class RequestDeliveryProbe: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private var sent = false

    /// Refuse to follow a redirect.
    ///
    /// URLSession follows them by default, so a captive portal or a proxy could
    /// answer 302 and have its landing page — anything containing `{"ok":true}`
    /// — credited with the rollback. `handle_ota_rollback` never redirects, so
    /// a redirect is proof this is not the kiln answering. Passing nil leaves
    /// the task holding the 3xx itself, which fails the 2xx check upstream.
    /// The web client sets `redirect: "manual"` for the same reason.
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest) async -> URLRequest? {
        nil
    }

    var requestWasSent: Bool {
        lock.lock()
        defer { lock.unlock() }
        return sent
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    didFinishCollecting metrics: URLSessionTaskMetrics) {
        let delivered = metrics.transactionMetrics.contains { $0.requestEndDate != nil }
        lock.lock()
        defer { lock.unlock() }
        sent = sent || delivered
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
