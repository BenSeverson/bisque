import SwiftUI

struct ProfileBuilderView: View {
    @Environment(KilnConnection.self) private var connection
    @Environment(KilnStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var viewModel = ProfileBuilderViewModel()
    @State private var mode: BuilderMode = .manual
    @State private var showConeWizard = false

    let existingProfile: FiringProfile?

    enum BuilderMode: String, CaseIterable {
        case manual = "Manual"
        case cone = "Cone Fire"
    }

    var body: some View {
        Form {
            Section("Mode") {
                Picker("Build Mode", selection: $mode) {
                    ForEach(BuilderMode.allCases, id: \.self) { m in
                        Text(m.rawValue).tag(m)
                    }
                }
                .pickerStyle(.segmented)
            }

            if mode == .manual {
                Section("Profile Info") {
                    TextField("Name", text: $viewModel.name)
                    TextField("Description", text: $viewModel.description)
                }

                Section("Stats") {
                    LabeledContent("Max Temp", value: "\(Int(viewModel.maxTemp))°C")
                    LabeledContent("Est. Duration", value: Formatters.formatDuration(seconds: viewModel.estimatedDuration * 60))
                }

                Section("Segments") {
                    ForEach(Array(viewModel.segments.enumerated()), id: \.element.id) { index, _ in
                        SegmentEditorView(segment: $viewModel.segments[index])
                    }
                    .onDelete { viewModel.segments.remove(atOffsets: $0) }
                    .onMove { viewModel.moveSegment(from: $0, to: $1) }

                    Button {
                        viewModel.addSegment()
                    } label: {
                        Label("Add Segment", systemImage: "plus.circle")
                    }
                }
            } else {
                ConeFireView(viewModel: viewModel)
            }

            if let error = viewModel.error {
                Section {
                    Text(error).foregroundStyle(.red)
                }
            }
        }
        .navigationTitle(existingProfile != nil ? "Edit Profile" : "New Profile")
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel") { dismiss() }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Save") {
                    guard let client = connection.apiClient else { return }
                    Task {
                        await viewModel.saveProfile(existingId: existingProfile?.id, using: client, store: store)
                        if viewModel.error == nil {
                            dismiss()
                        }
                    }
                }
                .disabled(viewModel.isSaving)
            }
        }
        .onAppear {
            if let profile = existingProfile {
                viewModel.loadForEditing(profile)
            }
        }
    }
}
