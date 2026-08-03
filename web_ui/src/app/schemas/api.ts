/**
 * Zod schemas for every REST-API response the frontend consumes, and the
 * TypeScript types derived from them. This is the canonical contract between
 * the firmware (which produces the JSON in components/web_server/api_json.c)
 * and the frontend (which parses it).
 *
 * The schemas are the *only* place a response shape is written down: the types
 * the app codes against are `z.infer`red from them here and re-exported by
 * services/api.ts and types/kiln.ts. Before that, the same shapes existed as
 * hand-written interfaces alongside these schemas with nothing tying the two
 * together, so only the schemas were contract-checked and the interfaces the
 * components actually used could drift freely (#176). Changing a schema now
 * fails the build at every call site that no longer matches.
 *
 * This lives under src/ rather than test/ for that reason — production code
 * derives from it. `z.infer` is type-only, so importing a schema purely for its
 * type costs nothing in the bundle.
 *
 * Two test suites validate against these schemas:
 *
 * 1. mock-server/handlers.test.ts spins up the TS mock-server in-process and
 *    asserts every endpoint matches — catches drift in the mock-server itself.
 * 2. test/contracts/firmwareContract.test.ts loads JSON fixtures emitted by
 *    the C test_api_json binary and asserts the firmware output matches —
 *    catches drift between firmware and frontend (Layer 3).
 *
 * Any time the frontend's expectations change, update these schemas plus the
 * matching C builder in api_json.c in the same PR.
 */
import { z } from "zod";

export const firingProgressResponseSchema = z.object({
  isActive: z.boolean(),
  profileId: z.string(),
  currentTemp: z.number(),
  targetTemp: z.number(),
  currentSegment: z.number(),
  totalSegments: z.number(),
  elapsedTime: z.number(),
  estimatedTimeRemaining: z.number(),
  /** Seconds until an armed delayed start fires; 0 when none is scheduled. */
  delayRemaining: z.number(),
  /** Live SSR duty as a whole percent, 0–100 (api_json.c `dutyPercent`). */
  dutyPercent: z.number().min(0).max(100),
  // Deliberately not the FiringStatus union: a status a newer firmware invents
  // must still parse, and coerceFiringStatus() in types/kiln.ts narrows it.
  status: z.string(),
  thermocouple: z.object({
    temperature: z.number(),
    internalTemp: z.number(),
    fault: z.boolean(),
    openCircuit: z.boolean(),
    shortGnd: z.boolean(),
    shortVcc: z.boolean(),
  }),
});

export type StatusResponse = z.infer<typeof firingProgressResponseSchema>;

export const coneEntrySchema = z.object({
  id: z.number(),
  name: z.string(),
  slowTempC: z.number(),
  mediumTempC: z.number(),
  fastTempC: z.number(),
});

export type ConeEntry = z.infer<typeof coneEntrySchema>;

export const historyRecordSchema = z.object({
  id: z.number(),
  /** Unix timestamp. */
  startTime: z.number(),
  profileName: z.string(),
  profileId: z.string(),
  peakTemp: z.number(),
  durationS: z.number(),
  outcome: z.enum(["complete", "error", "aborted"]),
  errorCode: z.number(),
});

export type HistoryRecord = z.infer<typeof historyRecordSchema>;

export const systemInfoSchema = z.object({
  firmware: z.string(),
  model: z.string(),
  uptimeSeconds: z.number(),
  freeHeap: z.number(),
  emergencyStop: z.boolean(),
  lastErrorCode: z.number(),
  elementHoursS: z.number(),
  spiffsTotal: z.number(),
  spiffsUsed: z.number(),
  boardTempC: z.number(),
});

export type SystemInfo = z.infer<typeof systemInfoSchema>;

export const autotuneStatusSchema = z.object({
  // Mirrors autotune_state_to_string in api_json.c. `failed` joined the set
  // when the firmware stopped flattening terminal outcomes onto `idle` (#216).
  state: z.enum(["idle", "running", "stopped", "complete", "failed"]),
  elapsedTime: z.number(),
  targetTemp: z.number(),
  currentTemp: z.number(),
  currentGains: z.object({
    kp: z.number(),
    ki: z.number(),
    kd: z.number(),
  }),
});

export type AutotuneStatus = z.infer<typeof autotuneStatusSchema>;

/**
 * Every `state` the firmware's build_autotune_status_json can emit.
 *
 * A union rather than a bare string (#217) so the transition table in
 * utils/autotuneSession.ts is checked at compile time instead of by runtime
 * string comparison — adding a state on the firmware side now fails the build
 * here until it is handled.
 */
export type AutotuneState = AutotuneStatus["state"];

/**
 * GET/POST /api/v1/pid — mirrors build_pid_json in api_json.c.
 *
 * `defaults` and `limits` are part of the contract precisely so the client
 * never hardcodes them: a client that mirrors the bounds drifts silently, and
 * the form goes on accepting values the controller answers with a bare 400.
 */
export const pidGainsResponseSchema = z.object({
  kp: z.number(),
  ki: z.number(),
  kd: z.number(),
});

export type PidGains = z.infer<typeof pidGainsResponseSchema>;

export const pidResponseSchema = pidGainsResponseSchema.extend({
  defaults: pidGainsResponseSchema,
  limits: z.object({
    min: z.number(),
    max: z.number(),
  }),
});

export type PidResponse = z.infer<typeof pidResponseSchema>;

export const thermocoupleDiagSchema = z.object({
  temperatureC: z.number(),
  internalTempC: z.number(),
  fault: z.boolean(),
  openCircuit: z.boolean(),
  shortGnd: z.boolean(),
  shortVcc: z.boolean(),
  readingAgeMs: z.number(),
  tcOffsetC: z.number(),
  temperatureAdjustedC: z.number(),
});

export type DiagThermocouple = z.infer<typeof thermocoupleDiagSchema>;
