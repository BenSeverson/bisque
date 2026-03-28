import SwiftUI

struct HistoryTab: View {
    @Environment(KilnConnection.self) private var connection
    @Environment(KilnStore.self) private var store
    @State private var viewModel = HistoryViewModel()

    var body: some View {
        NavigationStack {
            List {
                ForEach(store.history.sorted(by: { $0.startTime > $1.startTime })) { record in
                    NavigationLink(value: record) {
                        HistoryRecordRow(record: record, unit: store.settings.tempUnit)
                    }
                }
            }
            .navigationTitle("History")
            .navigationDestination(for: HistoryRecord.self) { record in
                HistoryDetailView(record: record, viewModel: viewModel)
            }
            .task {
                if let client = connection.apiClient {
                    await store.loadHistory(using: client)
                }
            }
            .refreshable {
                if let client = connection.apiClient {
                    await store.loadHistory(using: client)
                }
            }
            .overlay {
                if store.history.isEmpty && !store.isLoading {
                    ContentUnavailableView("No History", systemImage: "clock", description: Text("Completed firings will appear here"))
                }
            }
        }
    }
}

#Preview {
    HistoryTab()
        .environment(KilnConnection())
        .environment(KilnStore())
}
