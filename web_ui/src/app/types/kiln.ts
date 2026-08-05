/**
 * Shapes the firmware serves are inferred from their zod schemas rather than
 * restated as interfaces, so tightening a schema fails the build at every call
 * site that no longer matches (#176). The schema modules are imported for their
 * types only, which TypeScript erases — ../schemas/kiln imports the constants
 * below at runtime, and this direction of the pair must stay type-only or that
 * becomes a real module cycle.
 */
import type { ConeEntry, HistoryRecord } from "../schemas/api";
import type { firingProfileSchema, firingSegmentSchema, settingsSchema } from "../schemas/kiln";
import type { z } from "zod";

export type { ConeEntry, HistoryRecord };

/** Sentinel for FiringSegment.holdTime meaning "hold until operator skips."
 *  Mirrors FIRING_HOLD_INDEFINITE in firing_types.h. */
export const HOLD_UNTIL_SKIP = 65535;

/**
 * Smallest ramp-rate magnitude (°C/hr) a segment may carry, in either
 * direction. A client-side guardrail, not a firmware limit: `validate_profile`
 * (components/web_server/api_handlers.c) and the START guard
 * (components/firing_engine/firing_engine.c) only require a finite non-zero
 * rate, so 0.001°C/hr saves and starts happily — and a rate that small turns
 * a profile into a 1400-hour schedule whose chart path is unplottable (#160).
 *
 * 1°C/hr is chosen to sit well clear of both firmware boundaries around it:
 * the engine stops supervising a segment as a ramp below 0.1°C/hr (the runaway
 * check is gated on `fabsf(seg->ramp_rate) > 0.1f`), and its not-rising
 * watchdog trips unless a heating segment gains 10°C every 15 minutes — an
 * effective 40°C/hr floor for anything that runs to completion. Nothing the
 * device would actually fire is excluded.
 */
export const MIN_ABS_RAMP_RATE_C_PER_HR = 1;

/**
 * `rampRate` is degrees per hour, `targetTemp` degrees, `holdTime` minutes
 * (0 = no hold; HOLD_UNTIL_SKIP = hold until skip).
 */
export type FiringSegment = z.infer<typeof firingSegmentSchema>;

/** `estimatedDuration` is in minutes. */
export type FiringProfile = z.infer<typeof firingProfileSchema>;

export type FiringStatus =
  "idle" | "heating" | "holding" | "cooling" | "complete" | "error" | "paused" | "autotune";

const FIRING_STATUSES: ReadonlySet<FiringStatus> = new Set([
  "idle",
  "heating",
  "holding",
  "cooling",
  "complete",
  "error",
  "paused",
  "autotune",
]);

/** Coerce a server-provided status string into a FiringStatus, falling back to "idle". */
export function coerceFiringStatus(s: string | undefined | null): FiringStatus {
  return s && FIRING_STATUSES.has(s as FiringStatus) ? (s as FiringStatus) : "idle";
}

export interface FiringProgress {
  isActive: boolean;
  profileId: string | null;
  startTime: number | null;
  currentTemp: number;
  targetTemp: number;
  currentSegment: number;
  totalSegments: number;
  elapsedTime: number; // seconds
  estimatedTimeRemaining: number; // seconds
  /** Seconds until an armed delayed start fires; 0 when none is scheduled. */
  delayRemaining: number;
  /**
   * Element power: the SSR duty the kiln is driving right now, 0–100.
   *
   * Sourced from safety_get_ssr_duty() rather than the PID output, so it is
   * what the element is actually getting — 0 while an emergency stop holds the
   * output off, even if the controller is still asking for heat.
   *
   * `null` when the connected firmware predates #180 and sends no such field.
   * Distinct from 0, which means the element really is off: a kiln that cannot
   * report its power should say nothing rather than claim it is idle.
   */
  dutyPercent: number | null;
  status: FiringStatus;
}

/**
 * `apiToken` is write-only (sent only when changing the token); `apiTokenSet`
 * is the read side, reporting whether one is currently configured.
 */
export type KilnSettings = z.infer<typeof settingsSchema>;

/** Wi-Fi connection state (GET /api/v1/wifi), inferred from wifiInfoSchema. */
export type { WifiInfo } from "../schemas/api";

export interface TemperatureDataPoint {
  time: number; // minutes
  temp: number;
  target: number;
}
