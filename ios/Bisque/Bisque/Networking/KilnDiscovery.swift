import Foundation
import Network
import Observation

/// A kiln found on the local network and confirmed to speak the Bisque API.
struct DiscoveredKiln: Identifiable, Hashable, Sendable {
    /// The Bonjour instance name — "Bisque Kiln Controller", or
    /// "Bisque Kiln Controller (2)" once a second one joins the network, since
    /// Bonjour itself guarantees instance names are unique per network. That
    /// makes it a usable identity for the list even though the address behind
    /// it can change between DHCP leases.
    let serviceName: String
    let host: String
    let port: Int
    /// The kiln answered, but with 401 — it has an API token configured and the
    /// one we hold (if any) is not it.
    let requiresToken: Bool

    var id: String { serviceName }
}

/// Browses `_http._tcp` for kilns so the user does not have to type an address.
///
/// The firmware advertises mDNS with instance name "Bisque Kiln Controller" and
/// an `_http._tcp` service on port 80 (`main/main.c`), but it registers no TXT
/// record, so the browse alone cannot tell a kiln from a printer. Every result
/// is therefore probed with a real `GET /api/v1/status`, and only responders
/// that look like the firmware are listed. That doubles as a reachability
/// check: an entry in this list is one that will actually connect.
@MainActor @Observable
final class KilnDiscovery {
    enum State: Equatable {
        case idle
        case searching
        /// Browsing cannot proceed — almost always local-network permission.
        case failed(String)
    }

    private(set) var kilns: [DiscoveredKiln] = []
    private(set) var state: State = .idle

    /// How long to wait for a Bonjour service to resolve to an address, and for
    /// the verification request to answer. Deliberately shorter than
    /// `KilnAPIClient`'s 10s: this runs against every HTTP device on the
    /// network at once, and a device that has not answered in four seconds is
    /// not the one the user is standing next to.
    private static let resolveTimeout: TimeInterval = 4
    private static let probeTimeout: TimeInterval = 4

    private static let serviceType = "_http._tcp"

    private var browser: NWBrowser?
    /// One entry per Bonjour instance name we have started probing, kept after
    /// the probe finishes. The browse result set is re-delivered on every
    /// interface change, and a network with a dozen printers on it would
    /// otherwise re-probe all of them each time. Entries are dropped only when
    /// the service goes away, or wholesale by `restart()`.
    private var probes: [String: Task<Void, Never>] = [:]

    /// The token to present while probing, so a kiln we already have
    /// credentials for is listed as ready rather than locked. It is only ever
    /// sent to a service that has already identified itself — see `verify`.
    var apiToken: String?

    /// Bumped whenever the browser is torn down, so callbacks still in flight
    /// from the old one cannot act on the new one's state. `NWBrowser` delivers
    /// on its own queue and each handler hops to the main actor, so a
    /// `.cancelled` or a final result set from the browser `restart()` just
    /// replaced can otherwise land *after* its successor has reported `.ready`
    /// — resetting the state to idle, or wiping the new generation's kilns.
    private var generation = 0

    // MARK: - Lifecycle

    func start() {
        guard browser == nil else { return }

        state = .searching

        let parameters = NWParameters()
        parameters.includePeerToPeer = false

        let browser = NWBrowser(
            for: .bonjour(type: Self.serviceType, domain: nil),
            using: parameters)

        let generation = self.generation

        browser.stateUpdateHandler = { [weak self] state in
            Task { @MainActor in self?.handleBrowserState(state, generation: generation) }
        }

        browser.browseResultsChangedHandler = { [weak self] results, _ in
            // Map to plain strings inside the callback: only Sendable values
            // cross onto the main actor, and rebuilding the endpoint there from
            // name/type/domain resolves to the same service.
            //
            // The interface is dropped because there is none to keep: NWBrowser
            // collapses a service seen on several links into one result with a
            // nil endpoint interface and the links listed in `result.interfaces`
            // (verified against a live network — a kiln visible on lo0 and en0
            // arrives as a single result). Resolving with `interface: nil` then
            // lets the system pick a link that works.
            let services = results.compactMap { result -> BonjourService? in
                guard case let .service(name, type, domain, _) = result.endpoint else { return nil }
                return BonjourService(name: name, type: type, domain: domain)
            }
            Task { @MainActor in self?.handleResults(services, generation: generation) }
        }

        self.browser = browser
        browser.start(queue: .global(qos: .userInitiated))
    }

    func stop() {
        generation &+= 1
        browser?.cancel()
        browser = nil
        for probe in probes.values { probe.cancel() }
        probes.removeAll()
        state = .idle
    }

    /// Tears everything down and browses again from scratch.
    ///
    /// Bonjour caches aggressively, so a kiln that was powered on after the
    /// browse started can take a while to appear on its own; this is the
    /// user-facing escape hatch for that, and for retrying after the
    /// local-network prompt was answered.
    func restart() {
        stop()
        kilns.removeAll()
        start()
    }

    // MARK: - Browser plumbing

    private struct BonjourService: Sendable, Hashable {
        let name: String
        let type: String
        let domain: String
    }

    private func handleBrowserState(_ browserState: NWBrowser.State, generation: Int) {
        guard generation == self.generation else { return }
        switch browserState {
        case .ready:
            state = .searching
        case .waiting(let error), .failed(let error):
            // The overwhelmingly common cause is the user declining (or never
            // having been asked) the local-network prompt, which surfaces as a
            // DNS policy error rather than anything named "denied".
            state = .failed(Self.message(for: error))
        case .cancelled:
            state = .idle
        default:
            break
        }
    }

    private nonisolated static func message(for error: NWError) -> String {
        if case .dns(let code) = error, code == DNSServiceErrorType(kDNSServiceErr_PolicyDenied) {
            return "Allow Bisque to find devices on your local network in "
                + "Settings › Privacy & Security › Local Network, then search again."
        }
        return "Cannot search the local network (\(error.localizedDescription)). "
            + "Enter the kiln's address below."
    }

    private func handleResults(_ services: [BonjourService], generation: Int) {
        guard generation == self.generation else { return }
        let present = Set(services.map(\.name))

        // Drop anything that has gone away, along with its in-flight probe.
        for (name, probe) in probes where !present.contains(name) {
            probe.cancel()
            probes[name] = nil
        }
        kilns.removeAll { !present.contains($0.serviceName) }

        for service in services where probes[service.name] == nil {
            probes[service.name] = Task { [weak self] in
                await self?.probe(service)
            }
        }
    }

    /// Resolves one advertised service and keeps it only if it answers as a kiln.
    private func probe(_ service: BonjourService) async {
        let token = apiToken

        guard let resolved = await Self.resolve(service, timeout: Self.resolveTimeout),
              !Task.isCancelled else { return }

        let verdict = await Self.verify(
            host: resolved.host, port: resolved.port,
            serviceName: service.name, apiToken: token,
            timeout: Self.probeTimeout)
        guard !Task.isCancelled, let requiresToken = verdict else { return }

        let kiln = DiscoveredKiln(
            serviceName: service.name, host: resolved.host,
            port: resolved.port, requiresToken: requiresToken)

        if let existing = kilns.firstIndex(where: { $0.serviceName == kiln.serviceName }) {
            kilns[existing] = kiln
        } else {
            kilns.append(kiln)
            kilns.sort { $0.serviceName.localizedStandardCompare($1.serviceName) == .orderedAscending }
        }
    }

    // MARK: - Resolution

    /// Box for the one mutable flag in `resolve`. Every access happens on the
    /// connection's own serial queue, including the timeout, which is why the
    /// unchecked conformance is sound.
    private final class ResolveOnce: @unchecked Sendable {
        var done = false
    }

    /// Turns a Bonjour service into an address by connecting to it.
    ///
    /// `NWBrowser` hands back service *names*, not addresses, and there is no
    /// public resolve-only API — the supported route is to open a connection
    /// and read the resolved `remoteEndpoint` off its path once it is ready.
    private nonisolated static func resolve(
        _ service: BonjourService, timeout: TimeInterval
    ) async -> (host: String, port: Int)? {
        let queue = DispatchQueue(label: "com.bisque.discovery.resolve")
        let parameters = NWParameters.tcp
        parameters.includePeerToPeer = false

        let connection = NWConnection(
            to: .service(
                name: service.name, type: service.type,
                domain: service.domain, interface: nil),
            using: parameters)

        let once = ResolveOnce()

        return await withTaskCancellationHandler {
            await withCheckedContinuation { (continuation: CheckedContinuation<(host: String, port: Int)?, Never>) in
                let finish: @Sendable ((host: String, port: Int)?) -> Void = { value in
                    // Always called on `queue`.
                    guard !once.done else { return }
                    once.done = true
                    connection.stateUpdateHandler = nil
                    connection.cancel()
                    continuation.resume(returning: value)
                }

                connection.stateUpdateHandler = { state in
                    switch state {
                    case .ready:
                        finish(hostPort(from: connection.currentPath?.remoteEndpoint))
                    case .failed, .cancelled:
                        finish(nil)
                    default:
                        // `.waiting` is transient while a route comes up; let
                        // the timeout be the only deadline.
                        break
                    }
                }

                queue.asyncAfter(deadline: .now() + timeout) { finish(nil) }
                connection.start(queue: queue)
            }
        } onCancel: {
            connection.cancel()
        }
    }

    private nonisolated static func hostPort(from endpoint: NWEndpoint?) -> (host: String, port: Int)? {
        guard case let .hostPort(host, port) = endpoint,
              let hostString = urlHost(for: host) else { return nil }
        return (hostString, Int(port.rawValue))
    }

    /// Renders a resolved host in the form a URL will accept.
    ///
    /// Both address families arrive carrying a `%en0`-style zone id, which is
    /// meaningless in an IPv4 URL and needs literal-bracket plus percent-escape
    /// treatment (RFC 6874) in an IPv6 one.
    nonisolated static func urlHost(for host: NWEndpoint.Host) -> String? {
        switch host {
        case .ipv4(let address):
            return String("\(address)".split(separator: "%").first ?? "")
        case .ipv6(let address):
            let raw = "\(address)"
            guard let zoneStart = raw.firstIndex(of: "%") else { return "[\(raw)]" }
            let literal = raw[..<zoneStart]
            let zone = raw[raw.index(after: zoneStart)...]
            return "[\(literal)%25\(zone)]"
        case .name(let name, _):
            return name
        @unknown default:
            return nil
        }
    }

    // MARK: - Verification

    private enum ProbeOutcome {
        /// Answered `/api/v1/status` with something the app can decode.
        case kiln
        /// Answered 401, carrying whatever `WWW-Authenticate` it offered.
        case challenge(String)
        case other
    }

    /// Asks a candidate whether it is a kiln.
    ///
    /// Returns nil when it is not, otherwise whether it wants an API token.
    ///
    /// **The first request is always unauthenticated.** The browse enumerates
    /// every `_http._tcp` service on the network — printers, routers, cameras —
    /// and sending the saved bearer token to all of them would hand a
    /// kiln-controlling credential to anything that cared to log it. Only once
    /// a response has identified the peer as a kiln is the token presented, and
    /// then only to that peer.
    ///
    /// A 401 counts as identification when the challenge (or the advertised
    /// instance name) says Bisque — the firmware answers
    /// `WWW-Authenticate: Bearer realm="bisque"` — because otherwise every
    /// password-protected HTTP device on the network would list as a kiln.
    nonisolated static func verify(
        host: String, port: Int, serviceName: String,
        apiToken: String?, timeout: TimeInterval
    ) async -> Bool? {
        guard let url = URL(string: "http://\(host):\(port)/api/v1/status") else { return nil }

        switch await probeStatus(url: url, apiToken: nil, timeout: timeout) {
        case .kiln:
            return false
        case .other:
            return nil
        case .challenge(let challenge):
            let looksLikeBisque = challenge.lowercased().contains("bisque")
                || serviceName.lowercased().contains("bisque")
            guard looksLikeBisque else { return nil }
            guard let apiToken, !apiToken.isEmpty else { return true }

            // Identified as a kiln, so the token can go to it now. A second
            // challenge means the token we hold is not the one it wants.
            if case .kiln = await probeStatus(url: url, apiToken: apiToken, timeout: timeout) {
                return false
            }
            return true
        }
    }

    private nonisolated static func probeStatus(
        url: URL, apiToken: String?, timeout: TimeInterval
    ) async -> ProbeOutcome {
        var request = URLRequest(url: url)
        request.timeoutInterval = timeout
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        if let apiToken, !apiToken.isEmpty {
            request.setValue("Bearer \(apiToken)", forHTTPHeaderField: "Authorization")
        }

        guard let (data, response) = try? await URLSession.shared.data(for: request),
              let http = response as? HTTPURLResponse else { return .other }

        if http.statusCode == 401 {
            return .challenge(http.value(forHTTPHeaderField: "WWW-Authenticate") ?? "")
        }

        guard (200...299).contains(http.statusCode),
              (try? JSONDecoder().decode(StatusResponse.self, from: data)) != nil else { return .other }
        return .kiln
    }
}
