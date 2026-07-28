import { HOLD_UNTIL_SKIP, type FiringSegment, type TemperatureDataPoint } from "../types/kiln";
import { computeSegmentDurationMinutes } from "./profile";

/** Nominal resolution of the planned path: one point per 5 minutes of ramp. */
const MINUTES_PER_POINT = 5;

/** Floor, so a segment shorter than 50 minutes still draws as a line. */
const MIN_POINTS_PER_SEGMENT = 10;

/**
 * Ceiling on the ramp points of a whole path, independent of how long the
 * profile claims to be. The path feeds a Recharts line, which renders every
 * point; a 0.1°C/hr rate to 1300°C is a 780,000-minute ramp and produced
 * 153,601 points, blocking the main thread for ~60s (issue #160).
 *
 * A path returned by buildProfilePath holds at most
 * `MAX_PROFILE_PATH_POINTS + segments.length + 1` points: the ramp budget, one
 * end-of-hold point per segment, and the starting point.
 */
export const MAX_PROFILE_PATH_POINTS = 1000;

/**
 * Ceiling on the chart's hour ticks. Bounding the path is not enough on its
 * own: one tick per hour is 13,001 axis labels for the 0.1°C/hr profile above,
 * which Recharts lays out on the main thread (~20s) even when the line itself
 * holds a handful of points.
 */
export const MAX_PROFILE_AXIS_TICKS = 13;

/** Tick intervals in hours, in preference order, before falling back to a
 *  computed one. Keeps a long profile's labels on readable boundaries. */
const NICE_TICK_HOURS = [1, 2, 3, 4, 6, 8, 12, 24, 48, 72, 168];

/**
 * Time-axis domain and ticks for a planned path: whole hours, at most
 * MAX_PROFILE_AXIS_TICKS of them, with the last tick on the domain's end.
 *
 * An empty path yields no ticks — the caller leaves the axis on "auto" so the
 * live series alone still scales.
 */
export function buildProfileTimeAxis(path: readonly TemperatureDataPoint[]): {
  domainMax: number;
  ticks: number[];
} {
  const lastTime = path.length > 0 ? path[path.length - 1].time : 0;
  if (!Number.isFinite(lastTime) || lastTime <= 0) return { domainMax: 0, ticks: [] };

  const hours = Math.ceil(lastTime / 60);
  /* At least hours/(MAX-1) per step, so the tick count cannot exceed MAX
     however long the profile claims to be. */
  const minStepHours = Math.max(1, Math.ceil(hours / (MAX_PROFILE_AXIS_TICKS - 1)));
  const stepHours = NICE_TICK_HOURS.find((h) => h >= minStepHours) ?? minStepHours;

  const steps = Math.ceil(hours / stepHours);
  const ticks = Array.from({ length: steps + 1 }, (_, i) => i * stepHours * 60);
  return { domainMax: steps * stepHours * 60, ticks };
}

/**
 * Expand a profile's segments into the planned temperature/time path drawn
 * behind the live series on the dashboard chart.
 *
 * Two independent guards keep the point count sane, because the ramp rate that
 * drives it is user input: the schema's minimum magnitude (see
 * MIN_ABS_RAMP_RATE_C_PER_HR) stops new profiles carrying a near-zero rate, and
 * the budget here bounds the output for the ones already saved — including the
 * zero rate that makes the ramp duration non-finite.
 */
export function buildProfilePath(
  segments: readonly FiringSegment[],
  startTemp = 20,
): TemperatureDataPoint[] {
  if (segments.length === 0) return [];

  /* Split the budget across the segments so a profile's total stays bounded
     rather than each segment being free to spend the whole allowance. */
  const pointsPerSegment = Math.max(
    MIN_POINTS_PER_SEGMENT,
    Math.floor(MAX_PROFILE_PATH_POINTS / segments.length),
  );

  const path: TemperatureDataPoint[] = [{ time: 0, temp: startTemp, target: startTemp }];
  let currentTime = 0;
  let currentTemp = startTemp;

  for (const segment of segments) {
    const tempDifference = segment.targetTemp - currentTemp;
    const { rampMinutes } = computeSegmentDurationMinutes(
      {
        targetTemp: segment.targetTemp,
        rampRate: segment.rampRate,
        holdMinutes: segment.holdTime,
      },
      currentTemp,
    );
    /* A zero rate divides by zero: Infinity minutes, and `i <= Infinity` never
       terminates. Treat an unquantifiable ramp as instantaneous — the segment
       still contributes its temperature change to the path. */
    const rampTimeMinutes = Number.isFinite(rampMinutes) ? rampMinutes : 0;

    const steps = Math.min(
      pointsPerSegment,
      Math.max(MIN_POINTS_PER_SEGMENT, Math.floor(rampTimeMinutes / MINUTES_PER_POINT)),
    );
    for (let i = 1; i <= steps; i++) {
      const progress = i / steps;
      path.push({
        time: Math.round(currentTime + rampTimeMinutes * progress),
        temp: Math.round(currentTemp + tempDifference * progress),
        target: Math.round(currentTemp + tempDifference * progress),
      });
    }

    currentTime += rampTimeMinutes;
    currentTemp = segment.targetTemp;

    if (segment.holdTime > 0 && segment.holdTime !== HOLD_UNTIL_SKIP) {
      path.push({
        time: Math.round(currentTime + segment.holdTime),
        temp: segment.targetTemp,
        target: segment.targetTemp,
      });
      currentTime += segment.holdTime;
    }
  }

  return path;
}
