# Bisque iOS App — Design Spec

## Overview

Native SwiftUI iOS app for the Bisque kiln controller with full feature parity to the React web dashboard, plus iOS Live Activities for lock screen firing progress.

**Stack:** SwiftUI, URLSession, Swift Charts, ActivityKit
**Target:** iOS 17.0+ (Personal / TestFlight distribution)
**Connectivity:** Local Wi-Fi only (ESP32 AP or same LAN)
**Single kiln** at a time

## Project Structure

```
ios/Bisque/
  Bisque.xcodeproj
  Bisque/
    BisqueApp.swift                    # @main entry
    ContentView.swift                  # Connection gate + TabView

    Models/
      FiringProfile.swift              # id, name, description, segments[], maxTemp, estimatedDuration
      FiringSegment.swift              # id, name, rampRate, targetTemp, holdTime
      FiringProgress.swift             # isActive, currentTemp, targetTemp, status, segments, timing
      FiringStatus.swift               # Enum with color/label computed properties
      KilnSettings.swift               # tempUnit, maxSafeTemp, safety flags, webhook, costs
      HistoryRecord.swift              # id, startTime, profileName, peakTemp, outcome
      ConeEntry.swift                  # id, name, slow/medium/fastTempC
      SystemInfo.swift                 # firmware, uptime, heap, SPIFFS, boardTemp
      AutotuneStatus.swift             # state, elapsed, gains
      DiagThermocouple.swift           # temp, faults, readingAge
      StatusResponse.swift             # Full /status response
      WebSocketMessage.swift           # type discriminator + TempUpdateData

    Networking/
      KilnAPIClient.swift              # URLSession REST client, all 25 endpoints
      KilnWebSocketManager.swift       # URLSessionWebSocketTask, auto-reconnect
      APIError.swift                   # Typed error enum

    State/
      KilnConnection.swift             # @Observable: host, port, token, state
      KilnStore.swift                  # @Observable: progress, profiles, settings, history
      DashboardViewModel.swift         # Chart data, firing controls, profile path
      ProfilesViewModel.swift          # CRUD, import/export
      ProfileBuilderViewModel.swift    # Segment editing, cone fire wizard
      HistoryViewModel.swift           # Trace CSV parsing
      SettingsViewModel.swift          # Settings save, autotune, OTA

    Views/
      Connection/
        ConnectionView.swift           # IP entry, saved connections, test
      Dashboard/
        DashboardTab.swift             # Status + controls + chart
        TemperatureCardView.swift      # Big temp display
        FiringControlsView.swift       # Start/pause/stop/skip
        FiringChartView.swift          # Swift Charts actual vs target vs profile
      Profiles/
        ProfilesTab.swift              # Profile list
        ProfileCardView.swift          # Summary card
        ProfileDetailView.swift        # Full breakdown + actions
      ProfileBuilder/
        ProfileBuilderView.swift       # Manual + cone fire
        SegmentEditorView.swift        # Edit segment
        ConeFireView.swift             # Cone picker + options
      History/
        HistoryTab.swift               # Record list
        HistoryRecordRow.swift         # Compact row
        HistoryDetailView.swift        # Stats + trace chart
      Settings/
        SettingsTab.swift              # Grouped Form
        AutotuneView.swift             # PID autotune
        DiagnosticsView.swift          # TC read, relay test
        OTAUpdateView.swift            # Firmware upload
        AboutView.swift                # System info
      Shared/
        StatusBadge.swift              # Colored status pill
        TemperatureText.swift          # Formatted with unit
        TimeText.swift                 # Duration formatting
        ErrorBanner.swift              # Connection/error banner

    LiveActivity/
      FiringActivityAttributes.swift   # Shared with widget extension
      FiringActivityManager.swift      # Start/update/end lifecycle

    Notifications/
      NotificationManager.swift        # Local notifications for firing events

    Utilities/
      Formatters.swift                 # Temp/time formatting
      KeychainHelper.swift             # API token storage
      UserDefaultsKeys.swift           # Persisted preference keys
      TemperatureConverter.swift       # C<->F

    Preview Content/
      PreviewData.swift                # Mock data for Xcode previews

  BisqueLiveActivity/                  # Widget extension target
    BisqueLiveActivity.swift
    BisqueLiveActivityBundle.swift
    FiringLockScreenView.swift
    FiringDynamicIslandViews.swift
    Info.plist
    Assets.xcassets
```

## Navigation

Bottom tab bar with 4 tabs:
1. **Dashboard** (flame icon) — temperature, status, controls, chart
2. **Profiles** (doc icon) — profile list, builder, cone wizard
3. **History** (clock icon) — past firings, trace charts
4. **Settings** (gear icon) — all configuration

**Connection screen** shown on first launch or when disconnected. Auto-connects to last-used kiln on launch.

## Data Layer

### Models

All Swift structs with `Codable` conformance, matching the ESP32 JSON API exactly.

**FiringStatus** enum maps string status to display properties:
- `heating` → orange (#FFA500)
- `holding` → yellow (#FFFF00)
- `cooling` → blue (#4A90D9)
- `error` → red (#FF3B30)
- `complete` → green (#30D158)
- `paused` → yellow (#FFFF00)
- `idle` → secondary
- `autotune` → orange (#FFA500)

### API Client

`KilnAPIClient` — async/await REST client using `URLSession`:
- Generic `request<T: Decodable>(method:path:body:)` method
- 10-second timeout for all requests
- Optional Bearer token auth header
- Typed async method for each of the 25 endpoints
- OTA upload via `URLSessionUploadTask` with progress delegate
- History trace returns raw CSV text

### WebSocket

`KilnWebSocketManager` — `URLSessionWebSocketTask`:
- Connects to `ws://<host>/api/v1/ws`
- Receives `{ type: "temp_update", data: {...} }` JSON frames
- Auto-reconnect: 1s, 2s, 4s, max 8s backoff
- Publishes `lastUpdate: TempUpdateData?` and `isConnected: Bool`

## State Management

Using `@Observable` (iOS 17+):

**KilnConnection** — connection state, host/port/token, saved connections in UserDefaults, token in Keychain.

**KilnStore** — central state container:
- `progress: FiringProgress` — updated every WebSocket frame
- `profiles: [FiringProfile]` — fetched on connect
- `settings: KilnSettings` — fetched on connect
- `history: [HistoryRecord]` — fetched on demand
- `temperatureHistory: [TemperatureDataPoint]` — ring buffer (~200 points) for chart
- Triggers Live Activity updates and local notifications on status transitions

## Screen Details

### Dashboard
- Status badge (colored pill)
- Current temp (large), target temp, elapsed time
- Profile picker (disabled during firing) + delayed start stepper
- Start / Pause / Resume / Stop / Skip buttons (contextual)
- Current segment info with active indicator
- Swift Charts line chart: actual vs target vs profile path

### Profiles
- List of profile cards (name, maxTemp, duration, segment count)
- Profile detail: full segment list, Start / Edit / Duplicate / Export / Delete actions
- Profile builder: manual segment editor + cone fire wizard (sheet)
- Import via file picker (.json), export via share sheet

### History
- List of records sorted by date descending
- Record row: profile name, date, peak temp, outcome badge
- Detail view: stats cards + Swift Charts temperature trace
- CSV export via share sheet

### Settings
Native `Form` with sections:
- Temperature: unit (C/F), max safe temp, TC offset
- Safety: alarm, auto-shutdown toggles
- Notifications: toggle, webhook URL
- Energy: element watts, electricity cost
- API Security: token set/clear
- PID Auto-tune: setpoint, start/stop, live gains
- Diagnostics: TC reading, relay test
- Firmware: file picker + upload progress
- System Info: version, uptime, heap, SPIFFS, board temp

## Live Activity

### ActivityAttributes
```swift
struct FiringActivityAttributes: ActivityAttributes {
    let profileName: String
    let startTime: Date

    struct ContentState: Codable, Hashable {
        let currentTemp: Double
        let targetTemp: Double
        let status: String
        let currentSegment: Int
        let totalSegments: Int
        let progress: Double        // 0.0 - 1.0
        let estimatedSecondsRemaining: Int
    }
}
```

### Lock Screen
- Header: profile name (left), current temp large (right)
- Status: colored label (e.g., "Heating — Segment 2/3")
- Progress bar with gradient
- Footer: elapsed time (left), remaining time (right)

### Dynamic Island Compact
- Leading: 🔥 + current temp
- Trailing: remaining time

### Dynamic Island Expanded
- Profile name + status with color indicator
- Current temp (large) + target
- Segment info + ramp rate
- Full-width progress bar

### Lifecycle
- Started on `POST /firing/start` success
- Updated every WebSocket frame (~500ms)
- Ended on status → complete/error/idle

## Connection Flow

1. First launch → `ConnectionView` (enter IP)
2. "Connect" → test `GET /api/v1/status` (5s timeout)
3. 401 → prompt for token → retry
4. Success → save connection, start WebSocket, fetch all data
5. Auto-connect on subsequent launches (3s timeout before showing connection screen)
6. WebSocket disconnect → non-modal banner + auto-reconnect
7. Stale data indicator if no WS frame in >5 seconds during active firing

## Error Handling

- **Network errors**: Toast alerts for user actions, inline retry for data loading, persistent banner for connectivity
- **TC faults**: Red warning on Dashboard + local notification if backgrounded
- **Stale data**: "Data may be stale" indicator after 5s without WS frame
- **Auth errors**: 401 clears token, redirects to ConnectionView

## Local Notifications

Triggered on status transitions when app is backgrounded:
- **Complete**: "{profileName} finished. Peak: {temp}°C" (time-sensitive)
- **Error**: "{profileName} error — check kiln immediately" (time-sensitive)
- **Paused**: "{profileName} is paused" (optional)

## Implementation Phases

### Phase 1 — Foundation
1. Xcode project + both targets
2. All Codable models
3. KilnAPIClient (status + profiles endpoints first)
4. KilnWebSocketManager
5. KilnConnection + ConnectionView

### Phase 2 — Core Views
6. KilnStore central state
7. DashboardTab with temp display + controls
8. FiringChartView with Swift Charts
9. ProfilesTab with list + detail

### Phase 3 — Full Feature Parity
10. ProfileBuilder with segment editing + cone fire
11. HistoryTab with trace charts
12. SettingsTab (all sections)
13. Import/export via share sheet

### Phase 4 — iOS-Native Features
14. Live Activity (attributes, manager, widget views)
15. Local notifications
16. Keychain token storage
17. Auto-connect on launch

## Reference Files

- `web_ui/src/app/types/kiln.ts` — TypeScript types to port to Swift
- `web_ui/src/app/services/api.ts` — API client with all 25 endpoints
- `web_ui/src/app/services/websocket.ts` — WebSocket message format + reconnect logic
- `web_ui/src/app/components/FiringDashboard.tsx` — Dashboard state management + chart logic
- `components/web_server/ws_handler.c` — Server-side WS broadcast format (ground truth)
