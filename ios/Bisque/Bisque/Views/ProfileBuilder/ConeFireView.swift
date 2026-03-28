import SwiftUI

struct ConeFireView: View {
    @Bindable var viewModel: ProfileBuilderViewModel
    @Environment(KilnConnection.self) private var connection
    @Environment(KilnStore.self) private var store

    private let speeds = ["Slow", "Medium", "Fast"]

    var body: some View {
        Section("Cone Selection") {
            Picker("Cone", selection: $viewModel.selectedConeId) {
                Text("Select cone...").tag(nil as Int?)
                ForEach(viewModel.coneTable) { cone in
                    Text("Cone \(cone.name)").tag(cone.id as Int?)
                }
            }

            Picker("Speed", selection: $viewModel.coneSpeed) {
                ForEach(0..<3) { i in
                    Text(speeds[i]).tag(i)
                }
            }
            .pickerStyle(.segmented)
        }

        Section("Options") {
            Toggle("Preheat (80°C/hr to 120°C, 30 min hold)", isOn: $viewModel.conePreheat)
            Toggle("Slow Cool (-150°C/hr through 573°C)", isOn: $viewModel.coneSlowCool)
        }

        Section {
            Button("Generate Profile") {
                guard let client = connection.apiClient else { return }
                Task {
                    if let profile = await viewModel.generateConeFire(using: client) {
                        viewModel.name = profile.name
                        viewModel.description = profile.description
                        viewModel.segments = profile.segments
                    }
                }
            }
            .disabled(viewModel.selectedConeId == nil)
        }

        if !viewModel.segments.isEmpty {
            Section("Generated Segments") {
                ForEach(viewModel.segments) { segment in
                    VStack(alignment: .leading) {
                        Text(segment.name).font(.subheadline.bold())
                        Text("\(segment.rampRate > 0 ? "+" : "")\(Int(segment.rampRate))°C/hr → \(Int(segment.targetTemp))°C\(segment.holdTime > 0 ? ", hold \(Int(segment.holdTime))m" : "")")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }
}
