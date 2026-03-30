export function computeSegmentDurationMinutes(
  segment: { targetTemp: number; rampRate: number; holdMinutes: number },
  fromTemp: number,
): { rampMinutes: number; holdMinutes: number } {
  const tempDifference = Math.abs(segment.targetTemp - fromTemp);
  const rampTimeHours = tempDifference / Math.abs(segment.rampRate);
  const rampMinutes = rampTimeHours * 60;
  return { rampMinutes, holdMinutes: segment.holdMinutes };
}
