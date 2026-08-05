import { computeSegmentDurationMinutes, PROFILE_START_TEMP_C } from "./profile";

/**
 * Estimated electricity cost of a firing.
 *
 * The controller does not integrate energy — `elementHoursS` in /system is a
 * lifetime element-on total, not a per-firing figure — so everything here is an
 * estimate derived from the profile's shape, the configured element power and
 * the configured rate. It is deliberately labelled as such everywhere it is
 * shown; see COST_ESTIMATE_HINT.
 */

/**
 * Average SSR duty assumed while the element is working.
 *
 * A real duty cycle depends on the kiln's insulation, load and ambient
 * temperature, none of which the controller knows. 50% is the figure the
 * Settings copy has always quoted and is a reasonable average across a full
 * firing: ramps run near full power, holds only replace losses.
 *
 * Live duty *is* published (`dutyPercent`, #180) but only as an instantaneous
 * reading — turning it into energy needs the firmware to integrate it per
 * firing, which is what would replace this constant.
 */
export const ASSUMED_DUTY_CYCLE = 0.5;

export const COST_ESTIMATE_HINT =
  `Estimate only: ${Math.round(ASSUMED_DUTY_CYCLE * 100)}% average element duty over the heating ` +
  `portion of the firing, at the element power and electricity rate set in Settings. ` +
  `The controller does not meter actual energy use.`;

/** The settings fields a cost estimate needs. */
export interface CostSettings {
  elementWatts: number;
  electricityCostKwh: number;
}

/** The segments this needs; both `FiringProfile` and the builder's form rows fit. */
interface CostSegment {
  targetTemp: number;
  rampRate: number;
  /** `FiringProfile` calls this `holdTime`; the builder's form rows do too. */
  holdTime: number;
}

/**
 * Minutes of a profile during which the element is doing work.
 *
 * A *controlled cooling* segment (negative ramp rate) contributes nothing: the
 * kiln loses heat faster than the schedule asks for over most of its range, so
 * the element is essentially off. Counting it would put the 12-hour crystalline
 * profile — over three hours of which is a programmed cool — at nearly double
 * its real consumption.
 *
 * Holds always count, whatever precedes them, since maintaining a temperature
 * means replacing losses. An indefinite hold contributes 0 via
 * computeSegmentDurationMinutes, which is the same choice estimatedDuration
 * makes: its length is unknowable up front.
 */
export function heatingMinutes(segments: readonly CostSegment[]): number {
  let fromTemp = PROFILE_START_TEMP_C;
  let minutes = 0;
  for (const segment of segments) {
    const { rampMinutes, holdMinutes } = computeSegmentDurationMinutes(
      { targetTemp: segment.targetTemp, rampRate: segment.rampRate, holdMinutes: segment.holdTime },
      fromTemp,
    );
    if (segment.targetTemp > fromTemp) minutes += rampMinutes;
    minutes += holdMinutes;
    fromTemp = segment.targetTemp;
  }
  return minutes;
}

/** A profile, as far as costing it is concerned. */
export interface CostProfile {
  segments: readonly CostSegment[];
  /** Minutes, and the same number the UI shows as the profile's duration. */
  estimatedDuration: number;
}

/**
 * What share of a profile's wall-clock duration the element is working for.
 *
 * Deliberately a *fraction of the stored duration* rather than the raw heating
 * minutes. `estimatedDuration` is what every other part of the UI calls the
 * profile's length — the card, the builder summary, the firing progress bar —
 * and on the bundled profiles it is a hand-authored round number that the
 * segment arithmetic disagrees with (the shipped "Glaze Cone 6" stores 8h for
 * segments that work out to 10.8h). Pricing off the segments directly would put
 * a cost on the card that cannot be reconciled with the duration printed two
 * lines above it, so the segments only decide the *ratio*.
 *
 * Clamped to 1: a profile whose stored duration undercounts its own segments is
 * simply heating throughout.
 */
function heatingFraction(profile: CostProfile): number {
  if (!(profile.estimatedDuration > 0)) return 1;
  return Math.min(1, heatingMinutes(profile.segments) / profile.estimatedDuration);
}

/**
 * Cost in dollars of running the element for `heatingHours`, or null when the
 * estimate would be meaningless.
 *
 * Null rather than 0 for an unconfigured kiln: `elementWatts` or the rate left
 * at 0 means "not set up", and a confident "$0.00" on every profile is worse
 * than showing nothing.
 */
function costOfHeatingHours(heatingHours: number, settings: CostSettings): number | null {
  const { elementWatts, electricityCostKwh } = settings;
  if (!(elementWatts > 0) || !(electricityCostKwh > 0)) return null;
  if (!Number.isFinite(heatingHours) || heatingHours <= 0) return null;
  return (elementWatts / 1000) * heatingHours * ASSUMED_DUTY_CYCLE * electricityCostKwh;
}

/** Estimated cost of running a profile start to finish. */
export function estimateProfileCost(profile: CostProfile, settings: CostSettings): number | null {
  return costOfHeatingHours((profile.estimatedDuration / 60) * heatingFraction(profile), settings);
}

/**
 * Estimated cost of a completed firing.
 *
 * A history record carries only a total duration, which includes any programmed
 * cool. When the profile it ran is still on the kiln, its heating fraction is
 * applied so a record and its profile card quote the same number for a firing
 * that ran to plan; a record whose profile has since been deleted falls back to
 * the whole duration and therefore reads high on a profile with a long cool.
 */
export function estimateFiringCost(
  durationS: number,
  profile: CostProfile | undefined,
  settings: CostSettings,
): number | null {
  const hours = (durationS / 3600) * (profile ? heatingFraction(profile) : 1);
  return costOfHeatingHours(hours, settings);
}

/**
 * Cost per hour of running the element flat out — the one figure that needs no
 * assumption about the firing, so Settings can show the rate itself rather than
 * a number that depends on a schedule the user has not chosen yet.
 */
export function costPerHourAtFullPower(settings: CostSettings): number | null {
  const { elementWatts, electricityCostKwh } = settings;
  if (!(elementWatts > 0) || !(electricityCostKwh > 0)) return null;
  return (elementWatts / 1000) * electricityCostKwh;
}

/** Format dollars for display, e.g. `$4.20`. */
export function formatCost(dollars: number): string {
  return `$${dollars.toFixed(2)}`;
}
