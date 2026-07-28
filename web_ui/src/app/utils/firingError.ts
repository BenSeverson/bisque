/**
 * Human-readable copy for `firing_error_code_t`.
 *
 * The firmware reports a fault as a bare integer over the API. Until #164 the
 * web UI only ever rendered that integer ("Last Error Code: 3"), so the one
 * screen an operator reaches for after a failed firing was the one screen that
 * would not say what failed.
 *
 * The descriptions deliberately match `error_code_description()` in
 * `components/display/dashboard.c` word for word. Someone standing at the kiln
 * comparing the LCD to their phone should read one story, not two.
 *
 * Codes come off the wire, so an unknown value is expected rather than
 * exceptional — a controller on newer firmware can report a fault this build
 * has never heard of. Both functions degrade to the generic case instead of
 * throwing or leaking the integer.
 */

export const FIRING_ERROR_CODES = {
  NONE: 0,
  TC_FAULT: 1,
  OVER_TEMP: 2,
  NOT_RISING: 3,
  RUNAWAY: 4,
  EMERGENCY_STOP: 5,
  INVALID_PROFILE: 6,
} as const;

export type FiringErrorCode = (typeof FIRING_ERROR_CODES)[keyof typeof FIRING_ERROR_CODES];

/** Shown when the fault is unknown, absent, or genuinely unclassified. */
const GENERIC_DESCRIPTION = "Firing halted";

const DESCRIPTIONS: Record<number, string> = {
  [FIRING_ERROR_CODES.TC_FAULT]: "Thermocouple disconnected or shorted",
  [FIRING_ERROR_CODES.OVER_TEMP]: "Over temperature",
  [FIRING_ERROR_CODES.NOT_RISING]: "Kiln not heating",
  [FIRING_ERROR_CODES.RUNAWAY]: "Heating too fast",
  [FIRING_ERROR_CODES.EMERGENCY_STOP]: "Emergency stop",
  [FIRING_ERROR_CODES.INVALID_PROFILE]: "Profile invalid at this temperature",
};

/**
 * What went wrong, in the same words the LCD uses.
 * Never returns an empty string — callers can render it unconditionally.
 */
export function describeFiringError(code: number | undefined | null): string {
  if (code == null) return GENERIC_DESCRIPTION;
  return DESCRIPTIONS[code] ?? GENERIC_DESCRIPTION;
}

/**
 * What to do about it, for the faults with an actionable remedy.
 *
 * Returns `null` when there is nothing honest to add, so callers can omit the
 * line entirely rather than pad the UI with filler. Over-temp and runaway have
 * no single safe instruction from a phone — the operator needs to look at the
 * kiln — so they get a description and no false confidence.
 */
const GUIDANCE: Record<number, string> = {
  [FIRING_ERROR_CODES.TC_FAULT]:
    "Check the thermocouple wiring at both ends, then restart the firing.",
  [FIRING_ERROR_CODES.NOT_RISING]:
    "Check that the kiln has power and that the elements and relay are working.",
  // There is no "clear" control anywhere in the UI — starting a firing calls
  // safety_clear_emergency() (firing_engine.c:809), and safety_task re-trips
  // within 500 ms if the fault is still real. Say that, rather than sending
  // the operator looking for a button that does not exist.
  [FIRING_ERROR_CODES.EMERGENCY_STOP]:
    "Starting a new firing clears a stale stop. If the fault is still present, it trips again immediately.",
  [FIRING_ERROR_CODES.INVALID_PROFILE]:
    "The kiln was too hot for this profile's first segment. Let it cool, or edit the profile.",
};

export function firingErrorGuidance(code: number | undefined | null): string | null {
  if (code == null) return null;
  return GUIDANCE[code] ?? null;
}
