import SwiftUI

struct SettingsTab: View {
    @Environment(KilnConnection.self) private var connection
    @Environment(KilnStore.self) private var store
    @State private var viewModel = SettingsViewModel()
    @State private var localSettings: KilnSettings = .default
    @State private var hasLoaded = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Temperature") {
                    Picker("Unit", selection: $localSettings.tempUnit) {
                        Text("Celsius").tag("C")
                        Text("Fahrenheit").tag("F")
                    }
                    HStack {
                        Text("Max Safe Temp")
                        Spacer()
                        TextField("Max", value: $localSettings.maxSafeTemp, format: .number)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .frame(width: 80)
                        Text("°C")
                    }
                    HStack {
                        Text("TC Offset")
                        Spacer()
                        TextField("Offset", value: $localSettings.tcOffsetC, format: .number)
                            .keyboardType(.numbersAndPunctuation)
                            .multilineTextAlignment(.trailing)
                            .frame(width: 80)
                        Text("°C")
                    }
                }

                Section("Safety") {
                    Toggle("Alarm Enabled", isOn: $localSettings.alarmEnabled)
                    Toggle("Auto Shutdown", isOn: $localSettings.autoShutdown)
                    Toggle("Notifications", isOn: $localSettings.notificationsEnabled)
                }

                Section("Webhook") {
                    TextField("Webhook URL", text: $localSettings.webhookUrl)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                }

                Section("Energy") {
                    HStack {
                        Text("Element Watts")
                        Spacer()
                        TextField("Watts", value: $localSettings.elementWatts, format: .number)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .frame(width: 80)
                    }
                    HStack {
                        Text("Cost per kWh")
                        Spacer()
                        TextField("Cost", value: $localSettings.electricityCostKwh, format: .number)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .frame(width: 80)
                    }
                }

                Section("API Security") {
                    if localSettings.apiTokenSet == true {
                        Label("Token is set", systemImage: "lock.fill")
                            .foregroundStyle(.green)
                    }
                    Button("Change API Token") {
                        // Handle token change through connection
                    }
                }

                Section("PID Auto-Tune") {
                    NavigationLink("Auto-Tune") {
                        AutotuneView(viewModel: viewModel)
                    }
                }

                Section("Diagnostics") {
                    NavigationLink("Diagnostics") {
                        DiagnosticsView(viewModel: viewModel)
                    }
                }

                Section("Firmware") {
                    NavigationLink("OTA Update") {
                        OTAUpdateView(viewModel: viewModel)
                    }
                }

                Section("System") {
                    NavigationLink("System Info") {
                        AboutView()
                    }
                }

                Section {
                    Button("Save Settings") {
                        guard let client = connection.apiClient else { return }
                        Task { await viewModel.saveSettings(localSettings, using: client, store: store) }
                    }
                    .disabled(viewModel.isSaving)
                }

                Section {
                    Button("Disconnect", role: .destructive) {
                        connection.disconnect()
                    }
                }
            }
            .navigationTitle("Settings")
            .onAppear {
                if !hasLoaded {
                    localSettings = store.settings
                    hasLoaded = true
                }
            }
        }
    }
}

#Preview {
    SettingsTab()
        .environment(KilnConnection())
        .environment(KilnStore())
}
