import SwiftUI

struct ConnectionView: View {
    @Environment(KilnConnection.self) private var connection

    @State private var host: String = ""
    @State private var portString: String = ""
    @State private var showTokenField = false
    @State private var token: String = ""

    var body: some View {
        NavigationStack {
            VStack(spacing: 32) {
                Spacer()

                // Logo area
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

                // Connection form
                VStack(spacing: 16) {
                    HStack(spacing: 12) {
                        TextField("Kiln IP Address", text: $host)
                            .textFieldStyle(.roundedBorder)
                            .keyboardType(.decimalPad)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)

                        TextField("Port", text: $portString)
                            .textFieldStyle(.roundedBorder)
                            .keyboardType(.numberPad)
                            .frame(width: 72)
                    }
                    .onAppear {
                        host = connection.host
                        portString = String(connection.port)
                    }

                    if showTokenField {
                        SecureField("API Token (optional)", text: $token)
                            .textFieldStyle(.roundedBorder)
                            .onAppear { token = connection.apiToken ?? "" }
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

                // Connect button
                Button {
                    connection.host = host
                    connection.port = Int(portString) ?? 80
                    if !token.isEmpty {
                        connection.setAndSaveToken(token)
                    }
                    Task {
                        await connection.connect()
                    }
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

                // Error message
                if case .error(let message) = connection.connectionState {
                    Text(message)
                        .font(.callout)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal)
                }

                #if targetEnvironment(simulator)
                // Quick-connect to mock server
                Button {
                    host = "localhost"
                    portString = "8080"
                    connection.host = "localhost"
                    connection.port = 8080
                    Task {
                        await connection.connect()
                    }
                } label: {
                    HStack {
                        Image(systemName: "laptopcomputer")
                        Text("Use Mock Server (localhost:8080)")
                    }
                    .font(.callout)
                }
                .foregroundStyle(.secondary)
                .disabled(connection.connectionState == .connecting)
                #endif

                Spacer()
                Spacer()
            }
            .navigationTitle("")
        }
    }
}

#Preview {
    ConnectionView()
        .environment(KilnConnection())
}
