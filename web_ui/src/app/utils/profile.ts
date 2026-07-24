export function computeSegmentDurationMinutes(
  segment: { targetTemp: number; rampRate: number; holdMinutes: number },
  fromTemp: number,
): { rampMinutes: number; holdMinutes: number } {
  const tempDifference = Math.abs(segment.targetTemp - fromTemp);
  const rampTimeHours = tempDifference / Math.abs(segment.rampRate);
  const rampMinutes = rampTimeHours * 60;
  return { rampMinutes, holdMinutes: segment.holdMinutes };
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
