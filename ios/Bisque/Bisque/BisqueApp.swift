import SwiftUI

@main
struct BisqueApp: App {
    @State private var connection = KilnConnection()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(connection)
                .preferredColorScheme(.dark)
        }
    }
}
