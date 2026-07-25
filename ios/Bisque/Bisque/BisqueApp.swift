import SwiftUI

@main
struct BisqueApp: App {
    @State private var connection = KilnConnection()

    var body: some Scene {
        WindowGroup {
            // No .preferredColorScheme: the app follows the system setting like
            // any other iOS app, matching the web UI's theme handling (#155).
            // Every view uses semantic colours, so both schemes render correctly.
            ContentView()
                .environment(connection)
        }
    }
}
