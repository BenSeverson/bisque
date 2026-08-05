/** The firmware's own default when `hysteresis` is absent from the body. */
export const AUTOTUNE_DEFAULT_HYSTERESIS_C = 5;

export type AutotuneRequestResult =
  { ok: true; setpoint: number; hysteresis: number } | { ok: false; message: string };

/**
 * What the controller has told us about itself, for the checks that need more
 * than the two entered numbers. Every field is optional and its check is simply
 * skipped when absent — the same arrangement preparePidGains() uses for the
 * `limits` block, and for the same reason: the firmware stays the authority, so
 * a missing status frame must never harden into a mirrored constant here.
 */
export interface AutotuneLimits {
  /**
   * Latest reading in °C. Pass it only once a status frame has actually arrived
   * — the store seeds `currentTemp` to a synthetic 20 °C, and validating
   * against that would reject real requests on a cold page load.
   */
  currentTemp?: number;
  /** The configured over-temperature trip in °C (GET /settings maxSafeTemp). */
  maxSafeTemp?: number;
  /** Renders a °C value in the user's display unit, for the messages. */
  formatTemp?: (celsius: number) => string;
}

const defaultFormat = (celsius: number) => `${Math.round(celsius)}°C`;

/**
 * Validate an auto-tune start (POST /api/v1/autotune/start). Both values are in
 * Celsius, the unit the API takes.
 *
 * The firmware checks each field on its own — finite, positive, setpoint within
 * the max safe temp — but never looks at the pair, and the pairing is what
 * actually breaks a run. Every rule below is a way to get an accepted 200 that
 * then wastes the hour until the auto-tune timeout, or trips safety.
 *
 * The relay's two thresholds are what matter, not the band itself:
 * pid_autotune_update() switches the element ON below `setpoint - hysteresis`
 * and OFF above `setpoint + hysteresis`.
 */
export function prepareAutotuneRequest(
  setpoint: number,
  hysteresis: number,
  limits: AutotuneLimits = {},
): AutotuneRequestResult {
  const fmt = limits.formatTemp ?? defaultFormat;

  if (!Number.isFinite(setpoint) || setpoint <= 0) {
    return { ok: false, message: "Enter a setpoint above 0" };
  }
  if (!Number.isFinite(hysteresis) || hysteresis <= 0) {
    return { ok: false, message: "Enter a relay band above 0" };
  }

  const turnOn = setpoint - hysteresis;
  const turnOff = setpoint + hysteresis;

  // The floor that holds even with no status frame: a turn-on threshold at or
  // below 0 °C is unreachable for any kiln, so the element would never switch
  // on at all.
  if (turnOn <= 0) {
    return {
      ok: false,
      message: "The relay band must be smaller than the setpoint, or the element never switches on",
    };
  }

  // A tune drives the kiln to the *upper* threshold, not the setpoint, so the
  // firmware's own `setpoint > max_temp` check leaves the band free to overshoot
  // the trip. Reaching it means a safety stop and a latched error mid-tune.
  if (limits.maxSafeTemp !== undefined && Number.isFinite(limits.maxSafeTemp)) {
    if (turnOff > limits.maxSafeTemp) {
      return {
        ok: false,
        message: `The band would let the kiln reach ${fmt(turnOff)}, past the ${fmt(limits.maxSafeTemp)} safety limit — narrow the band or lower the setpoint`,
      };
    }
  }

  // The general form of the turn-on problem, which the 0 °C floor above only
  // catches at its extreme. pid_autotune_update() leaves its heat-up phase as
  // soon as `current_temp >= setpoint - hysteresis`, and enters relay cycling
  // with the element OFF. If the kiln is already past that threshold but still
  // below the setpoint, nothing will switch the element on until the reading
  // falls back under it — which passive cooling cannot do when the threshold is
  // below ambient. Starting from *above* the setpoint is fine and deliberately
  // allowed: it cools through the setpoint, crosses, and cycles normally.
  if (limits.currentTemp !== undefined && Number.isFinite(limits.currentTemp)) {
    const now = limits.currentTemp;
    if (now >= turnOn && now < setpoint) {
      return {
        ok: false,
        message: `The kiln is already at ${fmt(now)}, inside the band — the element would stay off. Narrow the band or raise the setpoint so heating starts below ${fmt(turnOn)}`,
      };
    }
  }

  return { ok: true, setpoint, hysteresis };
}
