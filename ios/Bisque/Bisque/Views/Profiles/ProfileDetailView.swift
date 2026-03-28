import SwiftUI

struct ProfileDetailView: View {
    @Environment(KilnConnection.self) private var connection
    @Environment(KilnStore.self) private var store
    @State private var viewModel = ProfilesViewModel()
    @State private var showBuilder = false
    @State private var showDeleteConfirm = false

    let profile: FiringProfile

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                // Info
                VStack(spacing: 8) {
                    Text(profile.description)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                    HStack(spacing: 20) {
                        VStack {
                            Text("\(Int(profile.maxTemp))°C")
                                .font(.title2.bold())
                            Text("Max Temp")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        VStack {
                            Text(Formatters.formatDuration(seconds: profile.estimatedDuration * 60))
                                .font(.title2.bold())
                            Text("Duration")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        VStack {
                            Text("\(profile.segments.count)")
                                .font(.title2.bold())
                            Text("Segments")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding()
                }

                // Segments
                SegmentListView(segments: profile.segments, currentSegment: -1, isActive: false)

                // Actions
                VStack(spacing: 12) {
                    HStack(spacing: 12) {
                        Button {
                            showBuilder = true
                        } label: {
                            Label("Edit", systemImage: "pencil")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)

                        Button {
                            guard let client = connection.apiClient else { return }
                            Task { await viewModel.duplicateProfile(profile, using: client, store: store) }
                        } label: {
                            Label("Duplicate", systemImage: "doc.on.doc")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                    }

                    if let data = viewModel.exportProfileData(profile) {
                        ShareLink(item: data, preview: SharePreview(profile.name, icon: "doc.text")) {
                            Label("Export JSON", systemImage: "square.and.arrow.up")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                    }

                    Button(role: .destructive) {
                        showDeleteConfirm = true
                    } label: {
                        Label("Delete", systemImage: "trash")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                }
                .padding(.horizontal)
            }
            .padding(.vertical)
        }
        .navigationTitle(profile.name)
        .sheet(isPresented: $showBuilder) {
            NavigationStack {
                ProfileBuilderView(existingProfile: profile)
            }
        }
        .confirmationDialog("Delete Profile?", isPresented: $showDeleteConfirm) {
            Button("Delete", role: .destructive) {
                guard let client = connection.apiClient else { return }
                Task { await viewModel.deleteProfile(id: profile.id, using: client, store: store) }
            }
        }
    }
}
