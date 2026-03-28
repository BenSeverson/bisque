import Foundation

enum PreviewData {
    static let segment = FiringSegment(
        id: "seg-1", name: "Ramp to 600°C",
        rampRate: 100, targetTemp: 600, holdTime: 30
    )

    static let segment2 = FiringSegment(
        id: "seg-2", name: "Ramp to 1060°C",
        rampRate: 150, targetTemp: 1060, holdTime: 15
    )

    static let segment3 = FiringSegment(
        id: "seg-3", name: "Cool Down",
        rampRate: -100, targetTemp: 500, holdTime: 0
    )

    static let profile = FiringProfile(
        id: "profile-1", name: "Bisque Cone 04",
        description: "Standard bisque firing to cone 04",
        segments: [segment, segment2, segment3],
        maxTemp: 1060, estimatedDuration: 480
    )

    static let profiles = [
        profile,
        FiringProfile(
            id: "profile-2", name: "Glaze Cone 6",
            description: "Mid-fire glaze firing",
            segments: [
                FiringSegment(id: "g1", name: "Slow Heat", rampRate: 80, targetTemp: 120, holdTime: 30),
                FiringSegment(id: "g2", name: "Ramp", rampRate: 150, targetTemp: 1222, holdTime: 10),
            ],
            maxTemp: 1222, estimatedDuration: 600
        ),
    ]

    static let progressIdle = FiringProgress.idle

    static let progressActive = FiringProgress(
        isActive: true, profileId: "profile-1", startTime: Date().timeIntervalSince1970,
        currentTemp: 1047, targetTemp: 1060, currentSegment: 1,
        totalSegments: 3, elapsedTime: 22320, estimatedTimeRemaining: 4980,
        status: "heating"
    )

    static let settings = KilnSettings.default

    static let historyRecord = HistoryRecord(
        id: 1, startTime: Date().timeIntervalSince1970 - 86400,
        profileName: "Bisque Cone 04", profileId: "profile-1",
        peakTemp: 1060, durationS: 28800, outcome: "complete", errorCode: 0
    )

    static let historyRecords = [
        historyRecord,
        HistoryRecord(
            id: 2, startTime: Date().timeIntervalSince1970 - 172800,
            profileName: "Glaze Cone 6", profileId: "profile-2",
            peakTemp: 1222, durationS: 36000, outcome: "complete", errorCode: 0
        ),
        HistoryRecord(
            id: 3, startTime: Date().timeIntervalSince1970 - 259200,
            profileName: "Test Fire", profileId: "profile-3",
            peakTemp: 450, durationS: 3600, outcome: "error", errorCode: 2
        ),
    ]

    static let systemInfo = SystemInfo(
        firmware: "1.2.0", model: "Bisque-S3",
        uptimeSeconds: 86400, freeHeap: 120000,
        emergencyStop: false, lastErrorCode: 0,
        elementHoursS: 360000, spiffsTotal: 1048576,
        spiffsUsed: 524288, boardTempC: 42.5
    )

    static let coneTable = [
        ConeEntry(id: 1, name: "022", slowTempC: 586, mediumTempC: 600, fastTempC: 614),
        ConeEntry(id: 2, name: "04", slowTempC: 1043, mediumTempC: 1060, fastTempC: 1070),
        ConeEntry(id: 3, name: "6", slowTempC: 1222, mediumTempC: 1240, fastTempC: 1263),
    ]
}
