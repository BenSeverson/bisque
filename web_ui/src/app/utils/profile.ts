import { HOLD_UNTIL_SKIP } from "../types/kiln";

/**
 * Temperature a profile is assumed to start from when estimating its shape.
 *
 * A cold kiln sits at room temperature, and the first segment's ramp has to
 * cover that distance. Used by both the duration estimate and the cost
 * estimate, which must walk the segments identically or a profile's quoted
 * cost stops matching its quoted duration.
 */
export const PROFILE_START_TEMP_C = 20;

export function computeSegmentDurationMinutes(
  segment: { targetTemp: number; rampRate: number; holdMinutes: number },
  fromTemp: number,
): { rampMinutes: number; holdMinutes: number } {
  const tempDifference = Math.abs(segment.targetTemp - fromTemp);
  const rampTimeHours = tempDifference / Math.abs(segment.rampRate);
  const rampMinutes = rampTimeHours * 60;
  // HOLD_UNTIL_SKIP is a sentinel meaning "hold until the operator skips", not
  // a duration. Summing it verbatim produced estimates around 45 days, which
  // were persisted into the profile's estimatedDuration and then pinned the
  // firing progress bar near 0% for the entire run. An indefinite hold
  // contributes nothing, since its length is unknowable up front.
  const holdMinutes = segment.holdMinutes === HOLD_UNTIL_SKIP ? 0 : segment.holdMinutes;
  return { rampMinutes, holdMinutes };
}

/**
 * Derive the id for a duplicated profile.
 *
 * The firmware's NVS key is the *first 15 characters* of the id with anything
 * outside [A-Za-z0-9_] replaced by '_', and a save whose key collides with a
 * different stored id is rejected with a 409. Appending a suffix (`${id}-copy-…`)
 * therefore never produced a distinct key for any id 15 chars or longer, so
 * duplicating a cone-fire or ProfileBuilder profile always failed on hardware.
 *
 * The unique token goes first so it lands inside those 15 characters — and so
 * the firmware's 40-char id field truncates the *tail* (the readable source id)
 * rather than the part that makes the key unique.
 */
export function makeDuplicateProfileId(sourceId: string): string {
  const token = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  return `c${token}-${sourceId}`.slice(0, 39);
}
