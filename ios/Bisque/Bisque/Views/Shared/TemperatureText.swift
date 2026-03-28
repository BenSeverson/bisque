import SwiftUI

struct TemperatureText: View {
    let tempC: Double
    var unit: String = "C"
    var style: Font = .body

    var body: some View {
        Text(Formatters.formatTemp(tempC, unit: unit))
            .font(style)
            .monospacedDigit()
    }
}
