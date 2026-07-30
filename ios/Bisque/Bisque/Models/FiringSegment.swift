import Foundation

/// Smallest usable ramp rate, as a magnitude so cooling segments (negative
/// rates) are held to the same floor.
///
/// Mirrors `MIN_ABS_RAMP_RATE_C_PER_HR` in `web_ui/src/app/types/kiln.ts`, so
/// the two clients accept the same profiles. Deliberately stricter than the
/// firmware, which only rejects zero and non-finite (`api_handlers.c`): 0.1°C/hr
/// passes that check and describes a 5800-hour firing.
let minAbsRampRateCPerHr: Double = 1

/// Ceiling on the chart path, matching the web UI's `MAX_PROFILE_PATH_POINTS`.
/// A legal-but-slow rate still implies tens of thousands of five-minute steps,
/// which is neither plottable nor worth allocating.
let maxProfilePathPoints = 2000

struct FiringSegment: Codable, Identifiable, Hashable {
    let id: String
    var name: String
    var rampRate: Double    // degrees per hour
    var targetTemp: Double  // degrees C
    var holdTime: Double    // minutes (0 = hold indefinitely)

    /// Why this segment cannot be charted or saved, or nil if it is fine.
    ///
    /// Checked before the arithmetic in `computeProfilePath` and
    /// `estimatedDuration`, both of which divide by `abs(rampRate)` (#143).
    var validationError: String? {
        guard rampRate.isFinite, targetTemp.isFinite, holdTime.isFinite else {
            return "\(name): values must be numbers"
        }
        guard abs(rampRate) >= minAbsRampRateCPerHr else {
            return "\(name): ramp rate must be at least \(Int(minAbsRampRateCPerHr))°C/hr to heat "
                + "or -\(Int(minAbsRampRateCPerHr))°C/hr to cool"
        }
        guard targetTemp > 0, targetTemp <= 1400 else {
            return "\(name): target temperature must be between 1 and 1400°C"
        }
        guard holdTime >= 0 else {
            return "\(name): hold time cannot be negative"
        }
        return nil
    }

    var formattedDescription: String {
        /* `Int(_:)` on a non-finite or out-of-range Double is a fatal error, not
           a garbage number — the same trap as #143, reachable here from a
           malformed profile decoded off the API rather than from the editor. */
        func whole(_ v: Double) -> String {
            v.isFinite && abs(v) < 1e9 ? String(Int(v)) : "—"
        }
        let sign = rampRate > 0 ? "+" : ""
        let hold = holdTime > 0 ? ", hold \(whole(holdTime))m" : ""
        return "\(sign)\(whole(rampRate))°C/hr → \(whole(targetTemp))°C\(hold)"
    }
}
