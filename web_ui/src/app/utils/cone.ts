import type { ConeEntry } from "../schemas/api";

/**
 * Nearest Orton cone to a profile's peak temperature.
 *
 * A cone measures heat work, not temperature, so the table gives three
 * temperatures per cone — one per ramp rate — and the answer depends on how
 * fast the profile arrives at its peak. `slowTempC`/`mediumTempC`/`fastTempC`
 * are the firmware's columns for these rates:
 */
const COLUMN_RATE_C_PER_HR = { slowTempC: 60, mediumTempC: 150, fastTempC: 300 } as const;

type ConeColumn = keyof typeof COLUMN_RATE_C_PER_HR;

/**
 * How close the peak ramp must sit to the slow or fast column's own rate
 * before that column is read instead of the standard one.
 *
 * Deliberately narrow. Published cone temperatures — the numbers people type
 * into a hand-built profile, and the ones the built-in profiles were authored
 * from — are the standard (`mediumTempC`) column's, whatever rate the profile
 * actually ramps at. Snapping to the nearest column instead would read the slow
 * column for the built-in "Glaze Cone 6" (80°C/hr to 1222°C) and label it
 * cone 7. Only a ramp genuinely at one of the extremes justifies leaving the
 * standard column, which is exactly what a Cone Fire Wizard profile does: its
 * final segment ramps at 60, 150 or 300°C/hr to that column's temperature.
 */
const COLUMN_SNAP_TOLERANCE = 0.2;

/**
 * Furthest a peak may sit from a cone's temperature and still be called that
 * cone. Adjacent cones are never more than ~47°C apart, so this only rejects
 * peaks off the ends of the table — a 300°C decal firing is not "≈ cone 022".
 */
const CONE_MATCH_TOLERANCE_C = 25;

/** The segments this needs; both `FiringProfile` and the builder's form rows fit. */
interface RampSegment {
  targetTemp: number;
  rampRate: number;
}

function columnForRampRate(rateCPerHr: number): ConeColumn {
  const rate = Math.abs(rateCPerHr);
  if (!Number.isFinite(rate) || rate === 0) return "mediumTempC";
  if (rate <= COLUMN_RATE_C_PER_HR.slowTempC * (1 + COLUMN_SNAP_TOLERANCE)) return "slowTempC";
  if (rate >= COLUMN_RATE_C_PER_HR.fastTempC * (1 - COLUMN_SNAP_TOLERANCE)) return "fastTempC";
  return "mediumTempC";
}

/**
 * Find the cone whose temperature is nearest `maxTempC`, or null when the
 * table is unavailable or nothing is close enough to be worth showing.
 */
export function coneEquivalent(
  maxTempC: number,
  segments: readonly RampSegment[],
  table: readonly ConeEntry[],
): ConeEntry | null {
  if (table.length === 0 || !Number.isFinite(maxTempC) || maxTempC <= 0) return null;

  // The ramp that reaches the peak sets the column; anything after it is a
  // cooling schedule and contributes no heat work to the cone.
  const peakSegment = segments.find((s) => s.targetTemp >= maxTempC);
  const column = columnForRampRate(peakSegment ? peakSegment.rampRate : Number.NaN);

  let nearest: ConeEntry | null = null;
  let nearestDelta = Infinity;
  for (const cone of table) {
    const delta = Math.abs(cone[column] - maxTempC);
    if (delta < nearestDelta) {
      nearestDelta = delta;
      nearest = cone;
    }
  }
  return nearestDelta <= CONE_MATCH_TOLERANCE_C ? nearest : null;
}

/** Tooltip for a rendered cone equivalent — it is heat work, not a promise. */
export const CONE_EQUIVALENT_HINT =
  "Nearest Orton cone to this profile's peak temperature and final ramp rate";

/** "≈ Cone 6", or null when there is no cone worth naming. */
export function coneEquivalentLabel(
  maxTempC: number,
  segments: readonly RampSegment[],
  table: readonly ConeEntry[],
): string | null {
  const cone = coneEquivalent(maxTempC, segments, table);
  return cone ? `≈ Cone ${cone.name}` : null;
}
