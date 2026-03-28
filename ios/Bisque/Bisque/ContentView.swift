import SwiftUI

struct ContentView: View {
    @Environment(KilnConnection.self) private var connection
    @State private var store = KilnStore()
    @State private var hasAttemptedAutoConnect = false

    var body: some View {
        Group {
            if connection.connectionState.isConnected {
                MainTabView()
                    .environment(store)
                    .task {
                        if let client = connection.apiClient {
                            store.subscribe(to: connection.webSocket)
                            store.notificationManager = NotificationManager()
                            store.activityManager = FiringActivityManager()
                            await store.refreshAll(using: client)
                        }
                    }
            } else {
                ConnectionView()
            }
        }
        .task {
            if !hasAttemptedAutoConnect {
                hasAttemptedAutoConnect = true
                await connection.autoConnect()
            }
        }
    }
}

struct MainTabView: View {
    var body: some View {
        TabView {
            DashboardTab()
                .tabItem {
                    Label("Dashboard", systemImage: "flame.fill")
                }
            ProfilesTab()
                .tabItem {
                    Label("Profiles", systemImage: "doc.text.fill")
                }
            HistoryTab()
                .tabItem {
                    Label("History", systemImage: "clock.arrow.circlepath")
                }
            SettingsTab()
                .tabItem {
                    Label("Settings", systemImage: "gearshape.fill")
                }
        }
        .tint(.orange)
    }
}

#Preview {
    ContentView()
        .environment(KilnConnection())
}
