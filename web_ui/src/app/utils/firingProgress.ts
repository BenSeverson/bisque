import { HOLD_UNTIL_SKIP } from "../types/kiln";

interface ProgressProfile {
  estimatedDuration: number; // minutes
  segments: { holdTime: number }[];
}

export interface FiringProgressResult {
  percent: number;
  /** False when the figure counts completed segments because the profile's
   *  total length is unknowable. Callers should say so rather than presenting
   *  it as a time percentage. */
  timeBased: boolean;
}

/**
 * How far through a firing we are.
 *
 * Elapsed-over-estimate only works when the estimate is real. A profile with a
 * hold-until-skip segment has no knowable length, so two things go wrong if it
 * is treated as an ordinary total: sitting in the indefinite hold past the
 * finite estimate reads 100% while later segments have not begun, and a profile
 * that is *only* an indefinite hold estimates to zero minutes — elapsed / 0 is
 * Infinity, which clamps to a confident 100% one second in.
 *
 * For those profiles the honest measure is completed segments: bounded,
 * monotonic, and never claims time it cannot know.
 */
export function computeFiringProgress(args: {
  profile: ProgressProfile | null;
  elapsedSeconds: number;
  currentSegment: number;
}): FiringProgressResult {
  const { profile, elapsedSeconds, currentSegment } = args;
  if (!profile) return { percent: 0, timeBased: false };

  const segmentCount = profile.segments.length;
  const hasIndefiniteHold = profile.segments.some((s) => s.holdTime === HOLD_UNTIL_SKIP);
  const totalSeconds = profile.estimatedDuration * 60;

  if (hasIndefiniteHold || totalSeconds <= 0) {
    if (segmentCount === 0) return { percent: 0, timeBased: false };
    const done = Math.max(0, Math.min(currentSegment, segmentCount));
    return { percent: (done / segmentCount) * 100, timeBased: false };
  }

  if (elapsedSeconds <= 0) return { percent: 0, timeBased: true };
  return { percent: Math.min(100, (elapsedSeconds / totalSeconds) * 100), timeBased: true };
}
