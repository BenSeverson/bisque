import SwiftUI

struct ContentView: View {
    @Environment(KilnConnection.self) private var connection
    @Environment(\.scenePhase) private var scenePhase
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
        /* iOS suspends the WebSocket within seconds of backgrounding, and the app
           declares no background modes. Without this the socket came back dead
           while connectionState still read .connected, so returning to the app
           mid-firing showed whatever reading it had when the phone went away —
           until the user happened to pull to refresh (#147).

           REST first, then the socket: the snapshot is what makes the screen
           correct immediately, and reconnecting alone would leave it wrong until
           the next broadcast. It is also the only place a transition that
           happened while suspended can be noticed, which is why refreshStatus
           runs it rather than just adopting the new value.

           refreshStatus, not refreshAll: the latter also awaits profiles and
           settings, so a stall on either would hold both the corrected reading
           and the socket restart behind an unrelated request. Those two change
           rarely and are refreshed on connect and on pull-to-refresh. */
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            Task {
                if let client = connection.apiClient {
                    await store.refreshStatus(using: client)
                }
                connection.resumeIfConnected()
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
