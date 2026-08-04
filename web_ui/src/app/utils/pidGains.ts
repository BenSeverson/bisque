import { pidGainsSchema } from "../schemas/kiln";
import type { PidGains } from "../services/api";

/** What the user typed, before it is known to be a number at all. */
export interface PidGainsDraft {
  kp: string;
  ki: string;
  kd: string;
}

export type PidGainsResult = { ok: true; gains: PidGains } | { ok: false; message: string };

/** The `limits` block of GET /api/v1/pid. */
export interface PidLimits {
  min: number;
  max: number;
}

const FIELD_LABEL: Record<keyof PidGainsDraft, string> = { kp: "Kp", ki: "Ki", kd: "Kd" };

/**
 * Turn three typed strings into gains the controller will accept, or a message
 * saying why not.
 *
 * The range check uses the limits the firmware served (GET /pid) rather than a
 * mirrored pair of constants: the two would drift, and the symptom of drift is
 * a form that accepts a value POST /pid answers with a bare 400 (#182). When
 * limits haven't arrived yet the range check is simply skipped — the shape and
 * "Kp or Ki must be positive" rules still apply, and the firmware remains the
 * authority either way.
 *
 * An empty field is called out by name. `Number("")` is 0, so without this an
 * unfilled Kd would silently submit as a real zero.
 */
export function preparePidGains(draft: PidGainsDraft, limits?: PidLimits): PidGainsResult {
  const parsedFields: Partial<PidGains> = {};
  for (const key of ["kp", "ki", "kd"] as const) {
    const raw = draft[key].trim();
    if (raw === "") {
      return { ok: false, message: `${FIELD_LABEL[key]} is required` };
    }
    parsedFields[key] = Number(raw);
  }

  const parsed = pidGainsSchema.safeParse(parsedFields);
  if (!parsed.success) {
    return { ok: false, message: parsed.error.issues[0]?.message ?? "Gains are invalid" };
  }

  if (limits) {
    for (const key of ["kp", "ki", "kd"] as const) {
      const value = parsed.data[key];
      if (value < limits.min || value > limits.max) {
        return {
          ok: false,
          message: `${FIELD_LABEL[key]} must be between ${limits.min} and ${limits.max}`,
        };
      }
    }
  }

  return { ok: true, gains: parsed.data };
}

/**
 * Render a gain for display and for seeding the edit fields.
 *
 * Four decimals is what NVS stores (int32 × 10000), so this is lossless for any
 * value the controller can actually hold. Trailing zeros are trimmed so a Kd of
 * 240 reads as "240" rather than "240.0000" — the fixed form is noise in a field
 * the user is about to retype.
 */
export function formatGain(value: number): string {
  if (!Number.isFinite(value)) return "--";
  return String(Number(value.toFixed(4)));
}
