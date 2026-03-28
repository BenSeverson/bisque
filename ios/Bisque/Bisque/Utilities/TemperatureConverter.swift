import Foundation

enum TemperatureConverter {
    static func cToF(_ celsius: Double) -> Double {
        celsius * 9.0 / 5.0 + 32.0
    }

    static func fToC(_ fahrenheit: Double) -> Double {
        (fahrenheit - 32.0) * 5.0 / 9.0
    }
}
