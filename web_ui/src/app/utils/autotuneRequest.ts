/** The firmware's own default when `hysteresis` is absent from the body. */
export const AUTOTUNE_DEFAULT_HYSTERESIS_C = 5;

export type AutotuneRequestResult =
  { ok: true; setpoint: number; hysteresis: number } | { ok: false; message: string };

/**
 * Validate an auto-tune start (POST /api/v1/autotune/start). Both values are in
 * Celsius, the unit the API takes.
 *
 * The firmware checks each field on its own — finite, positive, setpoint within
 * the max safe temp — but never compares the two, and the pairing is what
 * actually breaks a run. A hysteresis at or above the setpoint puts the relay's
 * turn-on threshold (`setpoint - hysteresis`) at or below 0 °C, so
 * pid_autotune_update() leaves HEATING_TO_SETPOINT on its first tick, finds
 * nothing that will ever satisfy `current_temp < setpoint - hysteresis`, and
 * holds the element off until the 60-minute timeout marks the tune FAILED. That
 * is an accepted 200 that wastes an hour, so it is worth refusing here.
 */
export function prepareAutotuneRequest(
  setpoint: number,
  hysteresis: number,
): AutotuneRequestResult {
  if (!Number.isFinite(setpoint) || setpoint <= 0) {
    return { ok: false, message: "Enter a setpoint above 0" };
  }
  if (!Number.isFinite(hysteresis) || hysteresis <= 0) {
    return { ok: false, message: "Enter a relay band above 0" };
  }
  if (hysteresis >= setpoint) {
    return {
      ok: false,
      message: "The relay band must be smaller than the setpoint, or the element never switches on",
    };
  }
  return { ok: true, setpoint, hysteresis };
}
