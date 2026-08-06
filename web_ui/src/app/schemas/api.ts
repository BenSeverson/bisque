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
  /**
   * Downdraft vent relay. Optional because the firmware omits it on a kiln with
   * no vent GPIO configured, which is the default — absent means "no vent
   * relay", not "vent off". */
  ventActive: z.boolean().optional(),
  /**
   * Lid/door interlock switch. Optional for the same reason `ventActive` is:
   * the firmware omits it entirely on a kiln with no lid GPIO configured, which
   * is the default — absent means "no lid switch", not "lid closed" (#83). */
  lidOpen: z.boolean().optional(),
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

/**
 * GET /api/v1/wifi — mirrors build_wifi_status_json in api_json.c.
 *
 * `savedSsid` is absent, not empty, when no credentials are stored: the setup
 * form keys off the key's presence. The passphrase is never part of the
 * response, and a host test asserts the builder can't start emitting one.
 */
export const wifiInfoSchema = z.object({
  connected: z.boolean(),
  apMode: z.boolean(),
  ip: z.string(),
  hasSavedCredentials: z.boolean(),
  savedSsid: z.string().optional(),
});

export type WifiInfo = z.infer<typeof wifiInfoSchema>;

/** POST /api/v1/ota/check — mirrors build_ota_check_json in api_json.c. */
export const otaCheckResponseSchema = z.object({
  current: z.string(),
  latest: z.string(),
  updateAvailable: z.boolean(),
  url: z.string(),
  sha256: z.string(),
  size: z.number(),
  notes: z.string(),
});

export type OtaCheckResponse = z.infer<typeof otaCheckResponseSchema>;

/**
 * GET /api/v1/ota/status — mirrors build_ota_status_json in api_json.c.
 *
 * Almost everything is optional because each part comes from a separate
 * esp_ota lookup in the handler and a failed lookup drops its key rather than
 * emitting a placeholder. `rollbackAvailable` is the one field always present.
 *
 * The partition sizes and build stamps are modelled even though no component
 * reads them yet: they *are* on the wire, and a schema that stops short of what
 * the firmware sends is a schema the contract test can't hold to `.strict()`.
 */
export const otaStatusSchema = z.object({
  running: z
    .object({
      label: z.string(),
      address: z.number(),
      size: z.number(),
      state: z.string().optional(),
      version: z.string().optional(),
      date: z.string().optional(),
      time: z.string().optional(),
      idfVersion: z.string().optional(),
    })
    .optional(),
  nextUpdate: z.object({ label: z.string(), size: z.number() }).optional(),
  bootPartition: z.string().optional(),
  /** Only emitted when the running partition's state was readable. */
  pendingVerify: z.boolean().optional(),
  rollbackAvailable: z.boolean(),
});

export type OtaStatus = z.infer<typeof otaStatusSchema>;

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
