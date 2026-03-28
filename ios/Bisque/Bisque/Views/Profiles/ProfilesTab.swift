import SwiftUI
import UniformTypeIdentifiers

struct ProfilesTab: View {
    @Environment(KilnConnection.self) private var connection
    @Environment(KilnStore.self) private var store
    @State private var viewModel = ProfilesViewModel()
    @State private var showBuilder = false
    @State private var editingProfile: FiringProfile?
    @State private var showImporter = false

    var body: some View {
        NavigationStack {
            List {
                ForEach(store.profiles) { profile in
                    NavigationLink(value: profile) {
                        ProfileCardView(profile: profile)
                    }
                }
            }
            .navigationTitle("Profiles")
            .navigationDestination(for: FiringProfile.self) { profile in
                ProfileDetailView(profile: profile)
            }
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Menu {
                        Button {
                            editingProfile = nil
                            showBuilder = true
                        } label: {
                            Label("New Profile", systemImage: "plus")
                        }
                        Button {
                            showImporter = true
                        } label: {
                            Label("Import JSON", systemImage: "square.and.arrow.down")
                        }
                    } label: {
                        Image(systemName: "plus")
                    }
                }
            }
            .sheet(isPresented: $showBuilder) {
                NavigationStack {
                    ProfileBuilderView(existingProfile: editingProfile)
                }
            }
            .fileImporter(isPresented: $showImporter, allowedContentTypes: [.json]) { result in
                switch result {
                case .success(let url):
                    guard url.startAccessingSecurityScopedResource() else { return }
                    defer { url.stopAccessingSecurityScopedResource() }
                    if let data = try? Data(contentsOf: url), let client = connection.apiClient {
                        Task { await viewModel.importProfile(from: data, using: client, store: store) }
                    }
                case .failure:
                    break
                }
            }
            .overlay {
                if store.profiles.isEmpty && !store.isLoading {
                    ContentUnavailableView("No Profiles", systemImage: "doc.text", description: Text("Create a firing profile to get started"))
                }
            }
        }
    }
}

#Preview {
    ProfilesTab()
        .environment(KilnConnection())
        .environment(KilnStore())
}
