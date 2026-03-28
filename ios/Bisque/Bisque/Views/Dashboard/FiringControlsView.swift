import SwiftUI

struct FiringControlsView: View {
    @Bindable var viewModel: DashboardViewModel
    let profiles: [FiringProfile]
    let progress: FiringProgress
    let client: KilnAPIClient?
    let store: KilnStore

    private var isActive: Bool { progress.isActive }
    private var isPaused: Bool { progress.status == "paused" }

    var body: some View {
        VStack(spacing: 12) {
            // Profile picker
            if !isActive && !isPaused {
                Picker("Profile", selection: $viewModel.selectedProfileId) {
                    Text("Select profile...").tag(nil as String?)
                    ForEach(profiles) { profile in
                        Text(profile.name).tag(profile.id as String?)
                    }
                }
                .pickerStyle(.menu)

                // Delay start
                Stepper("Delay: \(viewModel.delayMinutes) min", value: $viewModel.delayMinutes, in: 0...1440, step: 15)
                    .font(.callout)
            }

            // Action buttons
            HStack(spacing: 12) {
                if !isActive && !isPaused {
                    // Start
                    Button {
                        guard let client = client else { return }
                        Task { await viewModel.startFiring(using: client, store: store) }
                    } label: {
                        Label("Start", systemImage: "play.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.orange)
                    .disabled(viewModel.selectedProfileId == nil || viewModel.isStarting)
                } else if isPaused {
                    // Resume
                    Button {
                        guard let client = client else { return }
                        Task { await viewModel.pauseFiring(using: client) }
                    } label: {
                        Label("Resume", systemImage: "play.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.green)
                } else {
                    // Pause
                    Button {
                        guard let client = client else { return }
                        Task { await viewModel.pauseFiring(using: client) }
                    } label: {
                        Label("Pause", systemImage: "pause.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                }

                // Stop
                Button(role: .destructive) {
                    guard let client = client else { return }
                    Task { await viewModel.stopFiring(using: client, store: store) }
                } label: {
                    Label("Stop", systemImage: "stop.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(!isActive && !isPaused)

                // Skip segment
                if isActive && !isPaused {
                    Button {
                        guard let client = client else { return }
                        Task { await viewModel.skipSegment(using: client) }
                    } label: {
                        Label("Skip", systemImage: "forward.fill")
                    }
                    .buttonStyle(.bordered)
                }
            }

            // Error
            if let error = viewModel.actionError {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
        .padding()
        .background(Color(.systemGray6))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .padding(.horizontal)
    }
}
