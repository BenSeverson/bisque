import SwiftUI

struct TimeText: View {
    let seconds: Double

    var body: some View {
        Text(Formatters.formatDuration(seconds: seconds))
            .monospacedDigit()
    }
}
