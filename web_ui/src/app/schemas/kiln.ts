import { z } from "zod";
import { HOLD_UNTIL_SKIP, MIN_ABS_RAMP_RATE_C_PER_HR } from "../types/kiln";

// Reject NaN/Infinity that escape from `valueAsNumber: true` on empty inputs.
const finiteNumber = (msg: string) =>
  z.number({ message: msg }).refine(Number.isFinite, { message: msg });

/**
 * Firmware limits, mirrored so the builder rejects an over-size profile with a
 * clear message instead of letting the device silently truncate it or reject
 * the whole save with an opaque 400 (#135).
 *
 * `FIRING_MAX_SEGMENTS` is 16 and `FIRING_NAME_LEN` is 48 (47 chars + NUL) in
 * `components/firing_engine/include/firing_types.h`; api_handlers.c truncates
 * past the segment cap and rejects request bodies over 2048 bytes outright.
 */
export const MAX_SEGMENTS = 16;
export const MAX_NAME_LENGTH = 47;

/**
 * Largest request body `handle_post_profile()` will accept.
 *
 * It passes a `char buf[2048]` to `parse_body_json`, and `read_body` rejects
 * when `content_len >= buf_size` (api_handlers.c:381-389), so 2047 is the last
 * size that gets through.
 *
 * The field caps alone are not sufficient: 16 segments with 47-character names
 * serializes to 2075 bytes, 27 over the limit, so the maximum profile the
 * builder called valid was one the controller answered with an opaque 400 —
 * the exact failure those caps were added to prevent. It only bites at the
 * extreme; 16 segments with ordinary names is about 1372 bytes.
 */
export const MAX_PROFILE_BODY_BYTES = 2047;

/** Byte length of the serialized profile, which is what the firmware measures. */
export function profileBodyBytes(profile: unknown): number {
  return new TextEncoder().encode(JSON.stringify(profile)).length;
}

function checkBodySize(profile: unknown, ctx: z.RefinementCtx) {
  const bytes = profileBodyBytes(profile);
  if (bytes > MAX_PROFILE_BODY_BYTES) {
    ctx.addIssue({
      code: "custom",
      message: `Profile is too large for the controller (${bytes} bytes; limit ${MAX_PROFILE_BODY_BYTES}). Shorten the names or use fewer segments.`,
    });
  }
}

export const firingSegmentSchema = z.object({
  id: z.string(),
  name: z
    .string()
    .min(1, "Segment name is required")
    .max(MAX_NAME_LENGTH, `Segment name must be ${MAX_NAME_LENGTH} characters or fewer`),
  // A magnitude, so cooling segments (negative rates) are held to the same
  // floor. Only rejecting 0 let a typo like 0.1°C/hr through, which is a
  // 5800-hour firing and an unplottable chart path (#160).
  rampRate: finiteNumber("Ramp rate is required").refine(
    (v) => Math.abs(v) >= MIN_ABS_RAMP_RATE_C_PER_HR,
    {
      message: `Ramp rate must be at least ${MIN_ABS_RAMP_RATE_C_PER_HR}°C/hr to heat or -${MIN_ABS_RAMP_RATE_C_PER_HR}°C/hr to cool`,
    },
  ),
  targetTemp: finiteNumber("Target temp is required").gt(0).max(1400),
  holdTime: finiteNumber("Hold time is required").min(0).max(HOLD_UNTIL_SKIP),
});

export const profileFormSchema = z.object({
  name: z
    .string()
    .min(1, "Profile name is required")
    .max(MAX_NAME_LENGTH, `Profile name must be ${MAX_NAME_LENGTH} characters or fewer`),
  description: z.string(),
  segments: z
    .array(firingSegmentSchema)
    .min(1, "At least one segment is required")
    .max(MAX_SEGMENTS, `A profile can have at most ${MAX_SEGMENTS} segments`),
});

export type ProfileFormValues = z.infer<typeof profileFormSchema>;

/** Full profile shape used for import — must match FiringProfile in types/kiln.ts. */
export const firingProfileSchema = z
  .object({
    id: z.string().min(1, "Profile id is required"),
    name: z
      .string()
      .min(1, "Profile name is required")
      .max(MAX_NAME_LENGTH, `Profile name must be ${MAX_NAME_LENGTH} characters or fewer`),
    description: z.string(),
    segments: z
      .array(firingSegmentSchema)
      .min(1, "At least one segment is required")
      .max(MAX_SEGMENTS, `A profile can have at most ${MAX_SEGMENTS} segments`),
    maxTemp: z.number(),
    estimatedDuration: z.number(),
  })
  .superRefine(checkBodySize);

export const settingsSchema = z.object({
  tempUnit: z.enum(["C", "F"]),
  // Messages are user-facing: an immediate-save toggle surfaces the first issue
  // in a toast (see utils/settingsPatch.ts), where zod's built-in wording
  // ("Too big: expected number...") would not say which field is at fault.
  maxSafeTemp: finiteNumber("Max safe temperature is required")
    .min(0, "Max safe temperature cannot be negative")
    .max(1400, "Max safe temperature cannot exceed 1400 °C"),
  alarmEnabled: z.boolean(),
  autoShutdown: z.boolean(),
  notificationsEnabled: z.boolean(),
  tcOffsetC: finiteNumber("TC offset is required"),
  webhookUrl: z.string(),
  apiToken: z.string().optional(),
  apiTokenSet: z.boolean().optional(),
  elementWatts: finiteNumber("Element watts is required").min(
    0,
    "Element power cannot be negative",
  ),
  electricityCostKwh: finiteNumber("Electricity cost is required").min(
    0,
    "Electricity cost cannot be negative",
  ),
});

export type SettingsFormValues = z.infer<typeof settingsSchema>;

// Wi-Fi provisioning credentials. SSID 1–32 chars; WPA2 passphrase 0–63
// (empty allowed for open networks). Mirrors POST /api/v1/wifi.
export const wifiCredentialsSchema = z.object({
  ssid: z
    .string()
    .min(1, "Network name is required")
    .max(32, "SSID must be 32 characters or fewer"),
  password: z.string().max(63, "Password must be 63 characters or fewer"),
});

export type WifiCredentialsFormValues = z.infer<typeof wifiCredentialsSchema>;
