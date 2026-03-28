import SwiftUI
import Charts

struct FiringChartView: View {
    let temperatureHistory: [TemperatureDataPoint]
    let profilePath: [TemperatureDataPoint]
    let unit: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Temperature")
                .font(.headline)
                .padding(.horizontal)

            Chart {
                // Profile path
                ForEach(profilePath) { point in
                    LineMark(
                        x: .value("Time", point.time),
                        y: .value("Temp", unit == "F" ? TemperatureConverter.cToF(point.temp) : point.temp),
                        series: .value("Series", "Profile")
                    )
                    .foregroundStyle(.gray.opacity(0.5))
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                }

                // Current temperature
                ForEach(temperatureHistory) { point in
                    LineMark(
                        x: .value("Time", point.time),
                        y: .value("Temp", unit == "F" ? TemperatureConverter.cToF(point.temp) : point.temp),
                        series: .value("Series", "Current")
                    )
                    .foregroundStyle(.orange)
                    .lineStyle(StrokeStyle(lineWidth: 2))
                }

                // Target temperature
                ForEach(temperatureHistory) { point in
                    LineMark(
                        x: .value("Time", point.time),
                        y: .value("Temp", unit == "F" ? TemperatureConverter.cToF(point.target) : point.target),
                        series: .value("Series", "Target")
                    )
                    .foregroundStyle(.blue)
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [5, 5]))
                }
            }
            .chartXAxisLabel("Time (min)")
            .chartYAxisLabel("Temperature (°\(unit))")
            .chartLegend(position: .bottom)
            .frame(height: 250)
            .padding(.horizontal)
        }
        .padding(.vertical)
        .background(Color(.systemGray6))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .padding(.horizontal)
    }
}
