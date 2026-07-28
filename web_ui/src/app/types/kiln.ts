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

export interface FiringSegment {
  id: string;
  name: string;
  rampRate: number; // degrees per hour
  targetTemp: number; // degrees
  holdTime: number; // minutes (0 = no hold; HOLD_UNTIL_SKIP = hold until skip)
}

export interface FiringProfile {
  id: string;
  name: string;
  description: string;
  segments: FiringSegment[];
  maxTemp: number;
  estimatedDuration: number; // minutes
}

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
  status: FiringStatus;
}

export interface KilnSettings {
  tempUnit: "C" | "F";
  maxSafeTemp: number;
  alarmEnabled: boolean;
  autoShutdown: boolean;
  notificationsEnabled: boolean;
  tcOffsetC: number;
  webhookUrl: string;
  apiToken?: string; // write-only: only sent when changing the token
  apiTokenSet?: boolean; // read: whether a token is currently set
  elementWatts: number;
  electricityCostKwh: number;
}

/** Wi-Fi connection state, mirrors GET /api/v1/wifi (api_handlers.c handle_get_wifi). */
export interface WifiInfo {
  connected: boolean;
  apMode: boolean;
  ip: string;
  hasSavedCredentials: boolean;
  savedSsid?: string; // present only when credentials are saved
}

export interface TemperatureDataPoint {
  time: number; // minutes
  temp: number;
  target: number;
}

export interface ConeEntry {
  id: number;
  name: string;
  slowTempC: number;
  mediumTempC: number;
  fastTempC: number;
}

export interface HistoryRecord {
  id: number;
  startTime: number; // Unix timestamp
  profileName: string;
  profileId: string;
  peakTemp: number;
  durationS: number;
  outcome: "complete" | "error" | "aborted";
  errorCode: number;
}
