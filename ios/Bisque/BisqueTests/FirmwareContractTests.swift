import CryptoKit
import XCTest

@testable import Bisque

/// Cross-language API contract test for the iOS models (#154).
///
/// The C side (`tests/host/test_api_json.c`) drives each `build_*_json()`
/// helper with a fixture input and writes the resulting JSON to disk. The web
/// UI already asserts it can parse those bytes
/// (`web_ui/test/contracts/firmwareContract.test.ts`); until now the Swift
/// models decoded the same responses with no equivalent check, so a renamed or
/// retyped key was caught for one client and surfaced on the other only at
/// runtime, as a generic `APIError.decodingError`.
///
/// Fixtures come from `make fixtures`; `make test-ios` depends on that target.
/// Two things must not pass silently, for the same reasons they must not on the
/// web side (#173):
///
///   1. No fixtures at all — the suite would be green having validated
///      nothing. Missing fixtures fail; `BISQUE_SKIP_CONTRACTS=1 make test-ios`
///      is the explicit opt-out for a Mac that cannot run the C build. That
///      target both drops its `fixtures` prerequisite and re-exports the flag
///      as `TEST_RUNNER_BISQUE_SKIP_CONTRACTS`, which is the only form
///      `xcodebuild` forwards into a process on the simulator — set the plain
///      name on a bare `xcodebuild test` and it never arrives, so this reads
///      both.
///   2. Stale fixtures — JSON left over from an older serializer decodes fine.
///      `make fixtures` writes `_manifest.json` with a SHA256 of every source
///      that can change the emitted bytes; this re-hashes them and fails when
///      a digest has moved.
///
/// No `setUp`/`tearDown` overrides: they are nonisolated in the Xcode 16
/// XCTest and `@MainActor` in the Xcode 26 one, so an override touching test
/// state compiles on a current Mac and fails on CI.
final class FirmwareContractTests: XCTestCase {

    // MARK: - What each fixture is for

    /// Fixtures the app decodes, and the model it decodes them into.
    ///
    /// Every entry is a response `KilnAPIClient` or `KilnWebSocketManager`
    /// actually parses, decoded with a bare `JSONDecoder()` because that is
    /// what production uses — no key strategy, no date strategy.
    private static let decoded: [FixtureCase] = [
        .decoding("status", as: StatusResponse.self),
        .decoding("status_faulted", as: StatusResponse.self),
        // The optional-hardware variants. A kiln with no vent relay (#184) or no
        // lid switch (#83) — the firmware default for both — omits the field
        // entirely rather than sending false, so these prove the app still
        // decodes a status that is missing them.
        .decoding("status_no_vent", as: StatusResponse.self),
        .decoding("status_no_lid", as: StatusResponse.self),
        .decoding("status_lid_open", as: StatusResponse.self),
        .decoding("profile", as: FiringProfile.self),
        .decoding("profile_hold_until_skip", as: FiringProfile.self),
        .decoding("cone_fire_profiles", as: [FiringProfile].self),
        .decoding("settings", as: KilnSettings.self),
        .decoding("history_record", as: HistoryRecord.self),
        .decoding("history_empty", as: [HistoryRecord].self),
        .decoding("cone_table", as: [ConeEntry].self),
        .decoding("autotune_status", as: AutotuneStatus.self),
        .decoding("thermocouple_diag", as: DiagThermocouple.self),
        .decoding("system", as: SystemInfo.self),
        .decoding("system_emergency", as: SystemInfo.self),
        .decoding("ota_check", as: OtaCheckResponse.self),
        .decoding("ota_check_current", as: OtaCheckResponse.self),
        .decoding("ota_status", as: OtaStatus.self),
        // The same response with every optional lookup failed. It is what the
        // Firmware Partitions section renders against on a kiln that could not
        // describe its own running image, so it has to decode rather than throw
        // and take the whole OTA screen with it.
        .decoding("ota_status_minimal", as: OtaStatus.self),
        .decoding("ws_temp_update", as: WebSocketMessage.self),
        .decoding("ws_ota_progress", as: OTAWebSocketMessage.self),
        .decoding("ws_ota_complete", as: OTAWebSocketMessage.self),
        .decoding("ws_ota_error", as: OTAWebSocketMessage.self),
    ]

    /// Firmware responses the iOS app has no model for, and why.
    ///
    /// Listed rather than ignored so `testEveryFixtureIsClassified` can insist
    /// a *new* fixture be sorted into one list or the other. A fixture landing
    /// here is a deliberate statement that the app does not call that endpoint,
    /// not an oversight — the moment `KilnAPIClient` grows the call, it moves
    /// up into `decoded`.
    private static let notModelled: [String: String] = [
        "pid": "GET /pid — gains are edited from the web UI and the LCD only.",
        "wifi": "GET /wifi — provisioning is a web-UI/on-device flow.",
        "wifi_ap_mode": "GET /wifi in AP mode; same reason.",
    ]

    /// Keys the firmware emits that the Swift models deliberately drop.
    ///
    /// Unlike zod, `Codable` ignores unknown keys silently, so without this a
    /// new firmware field would sail through every test above and the app would
    /// go on not knowing it existed — the gap #174 closed for the web schemas.
    /// Paths are dot-separated, with `[]` for an array element.
    ///
    /// Emptying an entry is the goal, not the requirement: each line is a field
    /// the app could show and does not.
    private static let knownUnmodelled: [String: Set<String>] = [
        // The app shows neither the pre-start delay countdown nor the relay
        // duty cycle; the web dashboard shows both. It also shows neither piece
        // of optional hardware — the vent relay (#184) and the lid interlock
        // switch (#83) — both of which the LCD and the web dashboard do show.
        // Worth closing: an operator watching a firing from the app cannot
        // currently see that it paused because the lid is up.
        "status": ["delayRemaining", "dutyPercent", "ventActive", "lidOpen"],
        "status_faulted": ["delayRemaining", "dutyPercent", "ventActive"],
        "status_no_vent": ["delayRemaining", "dutyPercent"],
        "status_no_lid": ["delayRemaining", "dutyPercent"],
        "status_lid_open": ["delayRemaining", "dutyPercent", "ventActive", "lidOpen"],
        // Same as `status`, plus the id of the running profile — the app already
        // knows which profile it started, so the frame's copy is redundant to it.
        "ws_temp_update": [
            "data.delayRemaining", "data.dutyPercent", "data.profileId",
            "data.ventActive", "data.lidOpen",
        ],
        // The app does not offer the lid-mode setting; it is configured from the
        // web UI or the LCD.
        "settings": ["lidMode"],
    ]

    // MARK: - Decoding

    func testEveryModelledFixtureDecodes() throws {
        try requireUsableFixtures()

        for fixture in Self.decoded {
            let data = try Self.load(fixture.name)
            XCTAssertNoThrow(
                try fixture.decode(data),
                "\(fixture.name).json no longer decodes into the app's model. The firmware "
                    + "serializer and ios/Bisque/Bisque/Models/ have drifted apart."
            )
        }
    }

    /// A field the firmware gained that no Swift model claims.
    ///
    /// Reflection over the decoded value rather than the `CodingKeys` enum:
    /// every model here uses synthesized conformances, so the stored-property
    /// names *are* the JSON keys, and `Mirror` sees exactly those (computed
    /// properties like `HistoryRecord.startDate` are not stored, so they cannot
    /// masquerade as coverage).
    func testNoUnexpectedFirmwareFields() throws {
        try requireUsableFixtures()

        for fixture in Self.decoded {
            let data = try Self.load(fixture.name)
            let json = try JSONSerialization.jsonObject(with: data)
            let model = try fixture.decode(data)

            let found = Self.unmodelledKeys(json: json, model: model)
            let expected = Self.knownUnmodelled[fixture.name] ?? []

            XCTAssertEqual(
                found, expected,
                "\(fixture.name).json: the set of firmware keys with no Swift property has "
                    + "changed. Add the field to the model in ios/Bisque/Bisque/Models/, or, if "
                    + "the app genuinely has no use for it, record it in `knownUnmodelled`."
            )
        }
    }

    /// Every fixture on disk is either decoded above or explicitly excused.
    ///
    /// This is what makes a *new* endpoint visible: adding one to
    /// `test_api_json.c` fails here until someone decides whether iOS parses it.
    func testEveryFixtureIsClassified() throws {
        try requireUsableFixtures()

        let onDisk = try Self.fixtureNames()
        let claimed = Set(Self.decoded.map(\.name)).union(Self.notModelled.keys)

        XCTAssertEqual(
            onDisk.subtracting(claimed), [],
            "New firmware fixture(s) with no iOS verdict. Decode them in `decoded`, or record "
                + "in `notModelled` why the app does not call that endpoint."
        )
        XCTAssertEqual(
            claimed.subtracting(onDisk), [],
            "Fixture(s) named here no longer exist. The firmware dropped the response, or it "
                + "was renamed in tests/host/test_api_json.c."
        )
    }

    // MARK: - Values

    /*
     Decoding alone catches a renamed or retyped key. These pin the values down
     too, so a serializer that starts emitting a different field under the same
     name — a temperature in °F, seconds where minutes were — is a failure here
     rather than a wrong number on the phone.
     */

    func testStatusCarriesTheFiringAndThermocoupleState() throws {
        try requireUsableFixtures()
        let status = try Self.decode(StatusResponse.self, from: "status")

        XCTAssertTrue(status.isActive)
        XCTAssertEqual(status.profileId, "bisque-cone-04")
        XCTAssertEqual(status.currentTemp, 728.4, accuracy: 0.001)
        XCTAssertEqual(status.targetTemp, 1063, accuracy: 0.001)
        XCTAssertEqual(status.currentSegment, 2)
        XCTAssertEqual(status.totalSegments, 4)
        XCTAssertEqual(status.elapsedTime, 3600, accuracy: 0.001)
        XCTAssertEqual(status.estimatedTimeRemaining, 7200, accuracy: 0.001)
        XCTAssertEqual(status.status, "heating")
        XCTAssertEqual(FiringStatus(rawValue: status.status), .heating)

        XCTAssertEqual(status.thermocouple.temperature, 723.4, accuracy: 0.001)
        XCTAssertEqual(status.thermocouple.internalTemp, 28.5, accuracy: 0.001)
        XCTAssertFalse(status.thermocouple.fault)
    }

    /// The faulted response is the one the app has to render without a firing:
    /// empty profile id, zeroed counters, and the fault flags actually set.
    func testFaultedStatusDecodesWithItsFlags() throws {
        try requireUsableFixtures()
        let status = try Self.decode(StatusResponse.self, from: "status_faulted")

        XCTAssertFalse(status.isActive)
        XCTAssertEqual(status.profileId, "")
        XCTAssertEqual(status.status, "error")
        XCTAssertEqual(FiringStatus(rawValue: status.status), .error)
        XCTAssertTrue(status.thermocouple.fault)
        XCTAssertTrue(status.thermocouple.openCircuit)
        XCTAssertFalse(status.thermocouple.shortGnd)
        XCTAssertFalse(status.thermocouple.shortVcc)
    }

    func testProfileDecodesWithItsSegmentsInOrder() throws {
        try requireUsableFixtures()
        let profile = try Self.decode(FiringProfile.self, from: "profile")

        XCTAssertEqual(profile.id, "test-bisque")
        XCTAssertEqual(profile.name, "Test Bisque")
        XCTAssertEqual(profile.maxTemp, 1060, accuracy: 0.001)
        XCTAssertEqual(profile.estimatedDuration, 540, accuracy: 0.001)
        XCTAssertEqual(profile.segments.map(\.id), ["seg-1", "seg-2"])
        XCTAssertEqual(profile.segments[0].rampRate, 80, accuracy: 0.001)
        XCTAssertEqual(profile.segments[1].targetTemp, 1060, accuracy: 0.001)
        XCTAssertEqual(profile.segments[1].holdTime, 10, accuracy: 0.001)
    }

    /// 65535 is the firmware's hold-until-skip sentinel, not a 45-day hold.
    ///
    /// It arrives as an ordinary `holdTime`, so the only thing this can assert
    /// is that it survives decoding intact — but that is the part that would
    /// break if the field ever narrowed to something a `uint16` sentinel does
    /// not fit, and it is a value the segment formatter has to tolerate.
    func testHoldUntilSkipSentinelSurvivesDecoding() throws {
        try requireUsableFixtures()
        let profile = try Self.decode(FiringProfile.self, from: "profile_hold_until_skip")

        let segment = try XCTUnwrap(profile.segments.last)
        XCTAssertEqual(segment.holdTime, 65535, accuracy: 0.001)
        XCTAssertTrue(segment.isComputable)
        XCTAssertNil(segment.validationError)
    }

    /// Generated cone-fire profiles include cooling segments, whose negative
    /// ramp rates the builder's validation has to accept as-is (#143).
    func testConeFireProfilesDecodeIncludingCoolingSegments() throws {
        try requireUsableFixtures()
        let profiles = try Self.decode([FiringProfile].self, from: "cone_fire_profiles")

        XCTAssertEqual(profiles.map(\.id), ["cone-6-Slow", "cone-6-Medium", "cone-6-Fast"])

        let segments = profiles.flatMap(\.segments)
        XCTAssertFalse(segments.isEmpty)
        for segment in segments {
            XCTAssertTrue(segment.isComputable, "\(segment.name) is uncomputable as generated")
            XCTAssertNil(segment.validationError, "\(segment.name) fails the builder's validation")
        }
        XCTAssertTrue(
            segments.contains { $0.rampRate < 0 },
            "no cooling segment in the fixture — the negative-ramp path is untested"
        )
    }

    /// `apiToken` is write-only and `apiTokenSet` read-only, so a `GET
    /// /settings` must leave the first nil and the second populated.
    func testSettingsSplitsTheWriteOnlyTokenFromItsReadOnlyFlag() throws {
        try requireUsableFixtures()
        let settings = try Self.decode(KilnSettings.self, from: "settings")

        XCTAssertEqual(settings.tempUnit, "C")
        XCTAssertEqual(settings.maxSafeTemp, 1300, accuracy: 0.001)
        XCTAssertTrue(settings.alarmEnabled)
        XCTAssertFalse(settings.autoShutdown)
        XCTAssertEqual(settings.tcOffsetC, -2.5, accuracy: 0.001)
        XCTAssertEqual(settings.webhookUrl, "https://example.test/kiln")
        XCTAssertEqual(settings.elementWatts, 2400, accuracy: 0.001)
        XCTAssertEqual(settings.electricityCostKwh, 0.18, accuracy: 0.001)
        XCTAssertNil(settings.apiToken)
        XCTAssertEqual(settings.apiTokenSet, true)
    }

    func testHistoryRecordDecodesWithItsDerivedProperties() throws {
        try requireUsableFixtures()
        let record = try Self.decode(HistoryRecord.self, from: "history_record")

        XCTAssertEqual(record.id, 42)
        XCTAssertEqual(record.profileName, "Bisque Cone 04")
        XCTAssertEqual(record.profileId, "bisque-cone-04")
        XCTAssertEqual(record.peakTemp, 1063.5, accuracy: 0.001)
        XCTAssertEqual(record.durationS, 14400, accuracy: 0.001)
        XCTAssertEqual(record.outcome, "complete")
        XCTAssertEqual(record.errorCode, 0)
        XCTAssertTrue(record.isSuccess)
        XCTAssertEqual(record.startDate, Date(timeIntervalSince1970: 1_700_000_000))
    }

    /// An empty history is `[]`, not `null` or an envelope — the app renders it
    /// as an empty list rather than an error.
    func testEmptyHistoryDecodesAsAnEmptyArray() throws {
        try requireUsableFixtures()
        XCTAssertEqual(try Self.decode([HistoryRecord].self, from: "history_empty").count, 0)
    }

    func testConeTableDecodesWithThreeSpeedsPerCone() throws {
        try requireUsableFixtures()
        let cones = try Self.decode([ConeEntry].self, from: "cone_table")

        XCTAssertFalse(cones.isEmpty)
        XCTAssertEqual(cones.map(\.id), Array(0..<cones.count), "ids are the lookup index")

        let cone6 = try XCTUnwrap(cones.first { $0.name == "6" })
        XCTAssertEqual(cone6.slowTempC, 1201, accuracy: 0.001)
        XCTAssertEqual(cone6.mediumTempC, 1222, accuracy: 0.001)
        XCTAssertEqual(cone6.fastTempC, 1240, accuracy: 0.001)

        for cone in cones {
            XCTAssertLessThan(cone.slowTempC, cone.fastTempC, "cone \(cone.name)")
        }
    }

    func testAutotuneStatusCarriesNestedGains() throws {
        try requireUsableFixtures()
        let autotune = try Self.decode(AutotuneStatus.self, from: "autotune_status")

        XCTAssertEqual(autotune.state, "idle")
        XCTAssertEqual(autotune.currentTemp, 24, accuracy: 0.001)
        XCTAssertEqual(autotune.currentGains.kp, 2.5, accuracy: 0.001)
        XCTAssertEqual(autotune.currentGains.ki, 0.5, accuracy: 0.001)
        XCTAssertEqual(autotune.currentGains.kd, 1, accuracy: 0.001)
    }

    /// The diagnostics reading is distinct from `/status`: it exposes the raw
    /// and offset-adjusted temperatures separately, plus the reading's age.
    func testThermocoupleDiagnosticsKeepRawAndAdjustedApart() throws {
        try requireUsableFixtures()
        let diag = try Self.decode(DiagThermocouple.self, from: "thermocouple_diag")

        XCTAssertEqual(diag.temperatureC, 500, accuracy: 0.001)
        XCTAssertEqual(diag.temperatureAdjustedC, 498.5, accuracy: 0.001)
        XCTAssertEqual(diag.tcOffsetC, -1.5, accuracy: 0.001)
        XCTAssertEqual(diag.readingAgeMs, 250)
        XCTAssertTrue(diag.fault)
        XCTAssertTrue(diag.shortGnd)
    }

    func testSystemInfoDecodes() throws {
        try requireUsableFixtures()
        let info = try Self.decode(SystemInfo.self, from: "system")

        XCTAssertEqual(info.firmware, "1.4.2")
        XCTAssertEqual(info.model, "Bisque ESP32-S3")
        XCTAssertEqual(info.uptimeSeconds, 86412.5, accuracy: 0.001)
        XCTAssertEqual(info.freeHeap, 198_432)
        XCTAssertEqual(info.freeInternalHeap, 31_744)
        XCTAssertFalse(info.emergencyStop)
        XCTAssertEqual(info.elementHoursS, 151_200, accuracy: 0.001)
        XCTAssertEqual(info.spiffsTotal, 917_504)
        XCTAssertEqual(info.spiffsUsed, 233_472)
        XCTAssertEqual(info.boardTempC, 38.25, accuracy: 0.001)
    }

    func testSystemInfoReportsAnEmergencyStopWithItsErrorCode() throws {
        try requireUsableFixtures()
        let info = try Self.decode(SystemInfo.self, from: "system_emergency")

        XCTAssertTrue(info.emergencyStop)
        XCTAssertEqual(info.lastErrorCode, 7)
    }

    func testOtaCheckDecodesBothTheUpdateAndUpToDateShapes() throws {
        try requireUsableFixtures()

        let available = try Self.decode(OtaCheckResponse.self, from: "ota_check")
        XCTAssertTrue(available.updateAvailable)
        XCTAssertEqual(available.current, "1.4.2")
        XCTAssertEqual(available.latest, "1.5.0")
        XCTAssertEqual(available.size, 1_449_984)
        XCTAssertFalse(available.url.isEmpty)
        XCTAssertFalse(available.sha256.isEmpty)

        /* Up to date: the fields are emitted as empty strings and 0, not
           omitted, so the non-optional model still decodes. */
        let current = try Self.decode(OtaCheckResponse.self, from: "ota_check_current")
        XCTAssertFalse(current.updateAvailable)
        XCTAssertEqual(current.current, current.latest)
        XCTAssertEqual(current.url, "")
        XCTAssertEqual(current.size, 0)
    }

    /// The Firmware Partitions section (#177) reads five of these fields and
    /// gates a destructive button on a sixth, so each one is pinned rather than
    /// merely decoded.
    func testOtaStatusCarriesThePartitionStateTheAppActsOn() throws {
        try requireUsableFixtures()
        let status = try Self.decode(OtaStatus.self, from: "ota_status")

        XCTAssertEqual(status.running?.label, "ota_0")
        XCTAssertEqual(status.running?.version, "1.5.0")
        XCTAssertEqual(status.running?.state, "pending_verify")
        XCTAssertEqual(status.bootPartition, "ota_0")
        XCTAssertEqual(status.nextUpdate?.label, "ota_1")
        // `state` and `pendingVerify` come from one esp_ota lookup and always
        // agree; the app offers Confirm off the boolean, so a firmware that
        // let them diverge would put the button on screen for a valid image.
        XCTAssertEqual(status.pendingVerify, true)
        XCTAssertTrue(status.rollbackAvailable)
    }

    /// Every optional lookup failed, leaving `rollbackAvailable` alone on the
    /// wire. This is the shape that would crash a model with a non-optional
    /// `running`, and it is a real response — not a synthetic edge case.
    func testOtaStatusDecodesWithNothingButTheRollbackFlag() throws {
        try requireUsableFixtures()
        let status = try Self.decode(OtaStatus.self, from: "ota_status_minimal")

        XCTAssertNil(status.running)
        XCTAssertNil(status.nextUpdate)
        XCTAssertNil(status.bootPartition)
        // Absent, not false: the firmware emits it only alongside `state`, and
        // the app must not read the missing key as "not pending".
        XCTAssertNil(status.pendingVerify)
        XCTAssertFalse(status.rollbackAvailable)
    }

    func testTempUpdateFrameDecodes() throws {
        try requireUsableFixtures()
        let message = try Self.decode(WebSocketMessage.self, from: "ws_temp_update")

        XCTAssertEqual(message.type, "temp_update")
        XCTAssertTrue(message.data.isActive)
        XCTAssertEqual(message.data.currentTemp, 981.5, accuracy: 0.001)
        XCTAssertEqual(message.data.targetTemp, 1063, accuracy: 0.001)
        XCTAssertEqual(message.data.status, "holding")
        XCTAssertEqual(message.data.currentSegment, 3)
        XCTAssertEqual(message.data.totalSegments, 4)
        XCTAssertEqual(message.data.elapsedTime, 10800, accuracy: 0.001)
        XCTAssertEqual(message.data.estimatedTimeRemaining, 1800, accuracy: 0.001)
    }

    /// A temp_update frame must not decode as an OTA one, and vice versa —
    /// `KilnWebSocketManager` sniffs `type` and routes on it, so the three OTA
    /// frames have to produce the right `OTAEvent`.
    func testOtaFramesMapToTheirEvents() throws {
        try requireUsableFixtures()

        let progress = try Self.decode(OTAWebSocketMessage.self, from: "ws_ota_progress")
        XCTAssertEqual(progress.data.phase, "download")
        guard case .progress(let percent) = try XCTUnwrap(progress.event) else {
            return XCTFail("ota_progress did not map to .progress")
        }
        XCTAssertEqual(percent, 37, accuracy: 0.001)

        let complete = try Self.decode(OTAWebSocketMessage.self, from: "ws_ota_complete")
        guard case .complete = try XCTUnwrap(complete.event) else {
            return XCTFail("ota_complete did not map to .complete")
        }

        let failed = try Self.decode(OTAWebSocketMessage.self, from: "ws_ota_error")
        guard case .failed(let message) = try XCTUnwrap(failed.event) else {
            return XCTFail("ota_error did not map to .failed")
        }
        XCTAssertEqual(message, "SHA256 mismatch", "the device's reason must reach the user")
    }

    /// The envelope the manager decodes first, to decide which full decode to
    /// attempt. It has to read `type` off every frame, including ones whose
    /// payload it will never model.
    func testTypeEnvelopeReadsEveryFrame() throws {
        try requireUsableFixtures()

        let frames = ["ws_temp_update", "ws_ota_progress", "ws_ota_complete", "ws_ota_error"]
        let types = try frames.map { try Self.decode(WSTypeEnvelope.self, from: $0).type }
        XCTAssertEqual(types, ["temp_update", "ota_progress", "ota_complete", "ota_error"])
    }

    // MARK: - Fixture plumbing

    /// Sendable because `decoded` below is a `static let`, which Swift 6 treats
    /// as shared cross-actor state. Unchecked because the closure captures a
    /// metatype and the models are not declared `Sendable` — nothing here is
    /// mutable, and the closure does no more than construct a `JSONDecoder`.
    private struct FixtureCase: @unchecked Sendable {
        let name: String
        let decode: (Data) throws -> Any

        static func decoding<T: Decodable>(_ name: String, as _: T.Type) -> FixtureCase {
            FixtureCase(name: name) { try JSONDecoder().decode(T.self, from: $0) }
        }
    }

    private enum ContractError: Error {
        case unusableFixtures
    }

    private static let regenerate = "Run `make fixtures` (or `make test-ios`, which depends on it)."
    private static let optOut =
        "Set BISQUE_SKIP_CONTRACTS=1 (or TEST_RUNNER_BISQUE_SKIP_CONTRACTS=1 when driving "
        + "xcodebuild) to skip the firmware contract suite where the C build is unavailable."

    private static let skipContracts: Bool = {
        let env = ProcessInfo.processInfo.environment
        return env["BISQUE_SKIP_CONTRACTS"] == "1"
            || env["TEST_RUNNER_BISQUE_SKIP_CONTRACTS"] == "1"
    }()

    /// The checkout this test file was compiled from.
    ///
    /// `#filePath` rather than a bundled resource: the fixtures are build
    /// output under `tests/host/build/`, which does not exist when `xcodegen`
    /// generates the project, so it cannot be declared as a resource path. The
    /// simulator shares the Mac's filesystem, so the compile-time path is
    /// readable at run time — this is the same "read the generated JSON off
    /// disk" approach the Vitest contract test takes.
    private static let repoRoot: URL = {
        var url = URL(fileURLWithPath: #filePath)  // …/ios/Bisque/BisqueTests/<this file>
        for _ in 0..<4 { url.deleteLastPathComponent() }
        return url
    }()

    private static var fixtureDirectory: URL {
        repoRoot.appendingPathComponent("tests/host/build/fixtures/api")
    }

    /// Everything is checked up front so a broken fixture set is one actionable
    /// message rather than a cascade of "file not found" per test.
    private static let problem: String? = skipContracts ? nil : fixtureProblem()

    private func requireUsableFixtures() throws {
        if Self.skipContracts {
            throw XCTSkip(Self.optOut)
        }
        if let problem = Self.problem {
            XCTFail(problem)
            throw ContractError.unusableFixtures
        }
    }

    private static func load(_ name: String) throws -> Data {
        try Data(contentsOf: fixtureDirectory.appendingPathComponent("\(name).json"))
    }

    private static func decode<T: Decodable>(_ type: T.Type, from name: String) throws -> T {
        try JSONDecoder().decode(type, from: load(name))
    }

    /// Fixture names on disk, `_manifest.json` excluded — it is bookkeeping,
    /// not a response.
    private static func fixtureNames() throws -> Set<String> {
        let files = try FileManager.default.contentsOfDirectory(
            at: fixtureDirectory, includingPropertiesForKeys: nil)
        return Set(
            files
                .filter { $0.pathExtension == "json" && $0.lastPathComponent != "_manifest.json" }
                .map { $0.deletingPathExtension().lastPathComponent })
    }

    private static func sha256(of url: URL) throws -> String {
        SHA256.hash(data: try Data(contentsOf: url))
            .map { String(format: "%02x", $0) }
            .joined()
    }

    /// Repo-relative source paths from `tests/host/fixture_sources.txt`.
    private static func readSourceList() throws -> [String] {
        let path = repoRoot.appendingPathComponent("tests/host/fixture_sources.txt")
        return try String(contentsOf: path, encoding: .utf8)
            .split(separator: "\n", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty && !$0.hasPrefix("#") }
    }

    /// Why the fixtures can't be trusted, or nil when they can.
    private static func fixtureProblem() -> String? {
        let fileManager = FileManager.default

        guard fileManager.fileExists(atPath: fixtureDirectory.path) else {
            return "API fixtures not found at \(fixtureDirectory.path). \(regenerate)\n\(optOut)"
        }

        /* Before any individual load, so a half-generated directory is one
           message rather than a file-not-found per test. */
        let expected = Set(decoded.map(\.name)).union(notModelled.keys)
        let missing = expected.subtracting((try? fixtureNames()) ?? [])
        if !missing.isEmpty {
            let names = missing.sorted().map { "\($0).json" }.joined(separator: ", ")
            return "Incomplete API fixtures — missing \(names). \(regenerate)"
        }

        let manifestPath = fixtureDirectory.appendingPathComponent("_manifest.json")
        guard fileManager.fileExists(atPath: manifestPath.path) else {
            return "API fixtures have no _manifest.json, so their freshness can't be verified — "
                + "they predate the manifest or were written by hand. \(regenerate)"
        }

        let recorded: [String: String]
        do {
            let parsed = try JSONSerialization.jsonObject(with: Data(contentsOf: manifestPath))
            guard let sources = (parsed as? [String: Any])?["sources"] as? [String: String] else {
                return "Malformed fixture manifest at \(manifestPath.path) (no \"sources\" "
                    + "object). \(regenerate)"
            }
            recorded = sources
        } catch {
            return "Unreadable fixture manifest at \(manifestPath.path): \(error). \(regenerate)"
        }

        let listed: [String]
        do {
            listed = try readSourceList()
        } catch {
            return "Unreadable tests/host/fixture_sources.txt under \(repoRoot.path): \(error)"
        }

        var drifted: [String] = []
        for relative in listed {
            let absolute = repoRoot.appendingPathComponent(relative)
            guard fileManager.fileExists(atPath: absolute.path) else {
                return "\(relative) is listed in tests/host/fixture_sources.txt but does not "
                    + "exist. Update that list if the file moved or was removed."
            }
            guard let digest = recorded[relative] else {
                drifted.append(
                    "\(relative) (not covered by the manifest — the source list grew since "
                        + "generation)")
                continue
            }
            let actual = (try? sha256(of: absolute)) ?? ""
            if digest != actual {
                drifted.append("\(relative) (changed since generation)")
            }
        }

        /* A key the manifest has but the list no longer does means the manifest
           was built from a different source list, so nothing it records can be
           trusted: the removed file stops being hashed and every surviving
           digest still matches. Same reasoning as the Vitest side. */
        for relative in recorded.keys where !listed.contains(relative) {
            drifted.append(
                "\(relative) (recorded in the manifest but no longer listed — the source list "
                    + "shrank since generation)")
        }

        if !drifted.isEmpty {
            return "API fixtures are stale — the firmware serializers moved after they were "
                + "generated:\n  \(drifted.sorted().joined(separator: "\n  "))\n\(regenerate)"
        }

        return nil
    }

    // MARK: - Key coverage

    /// JSON key paths in `json` that `model` has no stored property for.
    ///
    /// Walks the two in parallel so nesting and arrays are handled without
    /// knowing the model's type: an array contributes the union of its
    /// elements' paths under `[]`, which keeps a 37-entry cone table from
    /// reporting the same missing key 37 times.
    private static func unmodelledKeys(json: Any, model: Any, path: String = "") -> Set<String> {
        guard let model = unwrapOptional(model) else { return [] }
        let mirror = Mirror(reflecting: model)

        if let object = json as? [String: Any] {
            /* Anything that isn't a struct is a leaf as far as coverage goes —
               a JSON object decoded into, say, a String has no properties to
               match, and reporting its keys would be noise. */
            guard mirror.displayStyle == .struct else { return [] }
            let properties = Dictionary(
                mirror.children.compactMap { child in child.label.map { ($0, child.value) } },
                uniquingKeysWith: { first, _ in first })

            var missing: Set<String> = []
            for (key, value) in object {
                let keyPath = path.isEmpty ? key : "\(path).\(key)"
                guard let property = properties[key] else {
                    missing.insert(keyPath)
                    continue
                }
                missing.formUnion(unmodelledKeys(json: value, model: property, path: keyPath))
            }
            return missing
        }

        if let array = json as? [Any], mirror.displayStyle == .collection {
            let elements = mirror.children.map(\.value)
            let elementPath = path.isEmpty ? "[]" : "\(path)[]"
            return zip(array, elements).reduce(into: Set<String>()) { missing, pair in
                missing.formUnion(unmodelledKeys(json: pair.0, model: pair.1, path: elementPath))
            }
        }

        return []
    }

    /// The wrapped value, or nil for `Optional.none`. Non-optionals pass through.
    private static func unwrapOptional(_ value: Any) -> Any? {
        let mirror = Mirror(reflecting: value)
        guard mirror.displayStyle == .optional else { return value }
        return mirror.children.first?.value
    }
}
