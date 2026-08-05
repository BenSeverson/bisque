/**
 * Zod schemas for every WebSocket frame the firmware pushes, and the types the
 * client codes against.
 *
 * Same arrangement as schemas/api.ts, and for the same reason: the frame shapes
 * were hand-written interfaces in services/websocket.ts with nothing tying them
 * to the firmware. `temp_update` is the highest-frequency payload in the whole
 * system and had neither a schema nor a fixture, so it was the least
 * contract-tested thing the device emits (#174).
 *
 * The firmware side is components/web_server/api_json.c —
 * build_ws_temp_update_json and build_ws_ota_event_json — and
 * test/contracts/firmwareContract.test.ts validates real fixtures from those
 * builders against these schemas.
 *
 * As with schemas/api.ts, nothing here is parsed at runtime: websocket.ts
 * imports the *types* only, so zod stays tree-shaken out of the shipped bundle.
 */
import { z } from "zod";

/**
 * `temp_update` — the periodic telemetry frame.
 *
 * `data` is the same progress block GET /status puts at its top level, minus the
 * thermocouple diagnostics; a host test asserts the two agree field-for-field.
 *
 * `profileId`, `delayRemaining` and `dutyPercent` are optional for firmware
 * compatibility, not because a current device omits them — a kiln running
 * firmware from before #180/#204 still parses, and the UI hides the reading
 * rather than claiming 0%. The contract test separately asserts that current
 * firmware does send all three.
 *
 * `ventActive` is the exception: current firmware genuinely omits it whenever
 * no vent GPIO is configured, so absent there means "this kiln has no vent
 * relay" rather than "old firmware" (#184).
 */
export const tempUpdateDataSchema = z.object({
  /** Present in every firmware frame but previously dropped by the client, so a
   *  firing started elsewhere left this tab on a stale profile. */
  profileId: z.string().optional(),
  currentTemp: z.number(),
  targetTemp: z.number(),
  // Deliberately not the FiringStatus union — see firingProgressResponseSchema.
  status: z.string(),
  currentSegment: z.number(),
  totalSegments: z.number(),
  elapsedTime: z.number(),
  estimatedTimeRemaining: z.number(),
  /** Seconds until an armed delayed start fires; 0 when none is scheduled. */
  delayRemaining: z.number().optional(),
  /** Live SSR duty as a whole percent, 0–100. */
  dutyPercent: z.number().min(0).max(100).optional(),
  /** Downdraft vent relay; absent when the kiln has no vent GPIO configured
   *  (the firmware default) — see firingProgressResponseSchema. */
  ventActive: z.boolean().optional(),
  isActive: z.boolean(),
});

export type TempUpdateData = z.infer<typeof tempUpdateDataSchema>;

/** `ota_progress` — emitted for both the download and the flash phase. */
export const otaProgressDataSchema = z.object({
  phase: z.enum(["download", "flash"]),
  percent: z.number(),
});

export type OtaProgressData = z.infer<typeof otaProgressDataSchema>;

/** `ota_complete` — `percent` is pinned at 100 by the firmware. */
export const otaCompleteDataSchema = z.object({
  percent: z.number(),
});

export type OtaCompleteData = z.infer<typeof otaCompleteDataSchema>;

/** `ota_error` — `message` is always present; the firmware substitutes a
 *  generic string rather than omitting the key, since this is what gets shown. */
export const otaErrorDataSchema = z.object({
  message: z.string(),
});

export type OtaErrorData = z.infer<typeof otaErrorDataSchema>;

export const wsMessageSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("temp_update"), data: tempUpdateDataSchema }),
  z.object({ type: z.literal("ota_progress"), data: otaProgressDataSchema }),
  z.object({ type: z.literal("ota_complete"), data: otaCompleteDataSchema }),
  z.object({ type: z.literal("ota_error"), data: otaErrorDataSchema }),
]);

export type WSMessage = z.infer<typeof wsMessageSchema>;
