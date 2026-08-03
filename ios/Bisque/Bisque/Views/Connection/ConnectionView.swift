import SwiftUI
import UIKit

struct ConnectionView: View {
    @Environment(KilnConnection.self) private var connection

    @State private var discovery = KilnDiscovery()
    @State private var host: String = ""
    @State private var portString: String = ""
    @State private var showTokenField = false
    @State private var token: String = ""
    /// Set when the token could not be written to the keychain. The connection
    /// still succeeds for this session; the warning is about the *next* launch,
    /// which used to fail with an unexplained "Authentication required" (#151).
    @State private var tokenSaveWarning: String?

    /// Offered when nothing has been connected to before. The firmware always
    /// advertises the `bisque` mDNS hostname, so on a single-kiln network this
    /// is one tap even if browsing turns up nothing (#153).
    private static let defaultHost = "bisque.local"

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 28) {
                    logo
                    discoverySection
                    manualEntrySection
                    connectButton
                    messages

                    #if targetEnvironment(simulator)
                    mockServerButton
                    #endif
                }
                .padding(.top, 48)
                .padding(.bottom, 32)
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("")
            .task {
                host = connection.host.isEmpty ? Self.defaultHost : connection.host
                portString = String(connection.port)
                discovery.apiToken = connection.apiToken
                discovery.start()
            }
            .onDisappear { discovery.stop() }
        }
    }

    // MARK: - Sections

    private var logo: some View {
        VStack(spacing: 8) {
            Image(systemName: "flame.fill")
                .font(.system(size: 64))
                .foregroundStyle(.orange)
            Text("Bisque")
                .font(.largeTitle.bold())
            Text("Kiln Controller")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    private var discoverySection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("On Your Network")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Button {
                    discovery.apiToken = connection.apiToken
                    discovery.restart()
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(.caption)
                }
                .foregroundStyle(.secondary)
                .accessibilityLabel("Search again")
            }

            if discovery.kilns.isEmpty {
                switch discovery.state {
                case .failed(let message):
                    VStack(alignment: .leading, spacing: 6) {
                        Text(message)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                        // Browsing is gated by the same permission a failed
                        // connection blames, so offer the same shortcut (#148).
                        if let settings = URL(string: UIApplication.openSettingsURLString) {
                            Link("Open Bisque Settings", destination: settings)
                                .font(.footnote)
                        }
                    }
                default:
                    HStack(spacing: 8) {
                        ProgressView()
                        Text("Searching for kilns…")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
            } else {
                ForEach(discovery.kilns) { kiln in
                    Button {
                        select(kiln)
                    } label: {
                        discoveredRow(kiln)
                    }
                    .buttonStyle(.plain)
                    .disabled(connection.connectionState == .connecting)
                }
            }
        }
        .padding(.horizontal, 40)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func discoveredRow(_ kiln: DiscoveredKiln) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "flame.circle.fill")
                .font(.title2)
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text(kiln.serviceName)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(.primary)
                Text("\(kiln.host):\(String(kiln.port))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if kiln.requiresToken {
                Image(systemName: "lock.fill")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .accessibilityLabel("Requires an API token")
            }
            Image(systemName: "chevron.right")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }
        .padding(12)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 10))
    }

    private var manualEntrySection: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Or Enter An Address")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)

            HStack(spacing: 12) {
                // Not a numeric keypad: the field takes `bisque.local` as
                // readily as an IP address, and a decimal pad cannot type it.
                TextField("bisque.local", text: $host)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.URL)
                    .textContentType(.URL)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)

                TextField("Port", text: $portString)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.numberPad)
                    .frame(width: 72)
            }

            if showTokenField {
                SecureField("API Token (optional)", text: $token)
                    .textFieldStyle(.roundedBorder)
                    .onAppear { if token.isEmpty { token = connection.apiToken ?? "" } }
            }

            Button {
                showTokenField.toggle()
            } label: {
                HStack {
                    Image(systemName: showTokenField ? "lock.fill" : "lock.open")
                    Text(showTokenField ? "Hide Token" : "Set API Token")
                }
                .font(.caption)
            }
            .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 40)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var connectButton: some View {
        Button {
            // Keep the service name when the field still holds the address the
            // connection is already using. Pressing Connect again after fixing
            // a token is not the same act as typing a new address, and dropping
            // the name there would quietly retire the DHCP fallback until the
            // user next picked the kiln out of discovery.
            let sameAddress = host == connection.host && Int(portString) == connection.port
            connect(
                host: host, port: Int(portString) ?? 80,
                serviceName: sameAddress ? connection.serviceName : nil)
        } label: {
            Group {
                if case .connecting = connection.connectionState {
                    ProgressView()
                        .tint(.black)
                } else {
                    Text("Connect")
                        .fontWeight(.semibold)
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 44)
        }
        .buttonStyle(.borderedProminent)
        .tint(.orange)
        .padding(.horizontal, 40)
        .disabled(host.isEmpty || connection.connectionState == .connecting)
    }

    @ViewBuilder
    private var messages: some View {
        if case .error(let message) = connection.connectionState {
            VStack(spacing: 8) {
                Text(message)
                    .font(.callout)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)

                // Settings → Privacy & Security → Local Network is several taps
                // deep and the app cannot read the permission, so the least it
                // can do is open the page where the toggle lives (#148).
                if connection.suggestsLocalNetworkPermission,
                   let settings = URL(string: UIApplication.openSettingsURLString) {
                    Link("Open Bisque Settings", destination: settings)
                        .font(.callout)
                }
            }
            .padding(.horizontal)
        }

        if let tokenSaveWarning {
            Text(tokenSaveWarning)
                .font(.callout)
                .foregroundStyle(.orange)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
        }
    }

    #if targetEnvironment(simulator)
    /// The mock server runs on the Mac, not on the network as a Bonjour
    /// service, so it can never turn up in the discovery list.
    private var mockServerButton: some View {
        Button {
            host = "localhost"
            portString = "8080"
            connect(host: "localhost", port: 8080)
        } label: {
            HStack {
                Image(systemName: "laptopcomputer")
                Text("Use Mock Server (localhost:8080)")
            }
            .font(.callout)
        }
        .foregroundStyle(.secondary)
        .disabled(connection.connectionState == .connecting)
    }
    #endif

    // MARK: - Actions

    /// Fills the manual fields from the tapped entry before connecting, so a
    /// failure leaves the user editing the address that failed rather than a
    /// stale one — and reveals the token field when the kiln asked for one.
    private func select(_ kiln: DiscoveredKiln) {
        host = kiln.host
        portString = String(kiln.port)
        if kiln.requiresToken {
            showTokenField = true
        }
        connect(host: kiln.host, port: kiln.port, serviceName: kiln.serviceName)
    }

    /// `serviceName` is nil for a hand-typed address and for the mock server:
    /// neither is tied to a Bonjour instance, so there is nothing to re-resolve
    /// them against later, and carrying a stale name over would send the app
    /// chasing a kiln the user just navigated away from.
    private func connect(host newHost: String, port newPort: Int, serviceName: String? = nil) {
        connection.host = newHost
        connection.port = newPort
        connection.serviceName = serviceName
        if !token.isEmpty {
            tokenSaveWarning =
                connection.setAndSaveToken(token)
                ? nil
                : "Connected, but the API token could not be saved to the keychain. You will need to enter it again next launch."
            discovery.apiToken = connection.apiToken
        }
        Task {
            await connection.connect()
            // `connect()` may have followed the kiln to a new address (#153).
            // Without adopting it here the field still shows the stale one, so
            // a user who fixes their token and presses Connect resubmits the
            // address that just failed — and, with no service name attached
            // this time, without the fallback that rescued it.
            host = connection.host
            portString = String(connection.port)
        }
    }
}

#Preview {
    ConnectionView()
        .environment(KilnConnection())
}
