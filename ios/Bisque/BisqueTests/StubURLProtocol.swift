import Foundation

/// Scripts HTTP replies and records what was actually sent.
///
/// `KilnDiscovery.verify` is a network classifier, so the interesting
/// assertions are as much about the requests it *makes* as the verdict it
/// returns — above all that a bearer token never leaves before the peer has
/// identified itself as a kiln.
final class StubURLProtocol: URLProtocol {
    struct Reply {
        var statusCode: Int = 200
        var headers: [String: String] = [:]
        var body: Data = Data()
        /// When set, the request fails at the transport layer instead of
        /// answering — a kiln that went off the network mid-probe.
        var error: Error?
    }

    private static let lock = NSLock()
    nonisolated(unsafe) private static var pending: [Reply] = []
    nonisolated(unsafe) private static var recorded: [URLRequest] = []

    /// Replaces the scripted replies and clears the record. Replies are handed
    /// out in order; a request past the end of the script fails, which keeps an
    /// unexpected extra request loud rather than silently satisfied.
    static func script(_ replies: [Reply]) {
        lock.lock()
        defer { lock.unlock() }
        pending = replies
        recorded = []
    }

    static var requests: [URLRequest] {
        lock.lock()
        defer { lock.unlock() }
        return recorded
    }

    /// The `Authorization` header of each request in order, nil where absent.
    static var authorizationHeaders: [String?] {
        requests.map { $0.value(forHTTPHeaderField: "Authorization") }
    }

    static func makeSession() -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubURLProtocol.self]
        return URLSession(configuration: config)
    }

    // MARK: - URLProtocol

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let reply: Reply? = {
            Self.lock.lock()
            defer { Self.lock.unlock() }
            Self.recorded.append(request)
            return Self.pending.isEmpty ? nil : Self.pending.removeFirst()
        }()

        guard let reply else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }

        if let error = reply.error {
            client?.urlProtocol(self, didFailWithError: error)
            return
        }

        guard let url = request.url,
              let response = HTTPURLResponse(
                url: url, statusCode: reply.statusCode,
                httpVersion: "HTTP/1.1", headerFields: reply.headers)
        else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }

        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: reply.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
