import { z } from "zod";
import { HOLD_UNTIL_SKIP } from "../types/kiln";

// Reject NaN/Infinity that escape from `valueAsNumber: true` on empty inputs.
const finiteNumber = (msg: string) =>
  z.number({ message: msg }).refine(Number.isFinite, { message: msg });

export const firingSegmentSchema = z.object({
  id: z.string(),
  name: z.string().min(1, "Segment name is required"),
  rampRate: finiteNumber("Ramp rate is required").refine((v) => v !== 0, {
    message: "Ramp rate must be non-zero",
  }),
  targetTemp: finiteNumber("Target temp is required").gt(0).max(1400),
  holdTime: finiteNumber("Hold time is required").min(0).max(HOLD_UNTIL_SKIP),
});

export const profileFormSchema = z.object({
  name: z.string().min(1, "Profile name is required"),
  description: z.string(),
  segments: z.array(firingSegmentSchema).min(1, "At least one segment is required"),
});

export type ProfileFormValues = z.infer<typeof profileFormSchema>;

/** Full profile shape used for import — must match FiringProfile in types/kiln.ts. */
export const firingProfileSchema = z.object({
  id: z.string().min(1, "Profile id is required"),
  name: z.string().min(1, "Profile name is required"),
  description: z.string(),
  segments: z.array(firingSegmentSchema).min(1, "At least one segment is required"),
  maxTemp: z.number(),
  estimatedDuration: z.number(),
});

export const settingsSchema = z.object({
  tempUnit: z.enum(["C", "F"]),
  maxSafeTemp: finiteNumber("Max safe temperature is required").min(0).max(1400),
  alarmEnabled: z.boolean(),
  autoShutdown: z.boolean(),
  notificationsEnabled: z.boolean(),
  tcOffsetC: finiteNumber("TC offset is required"),
  webhookUrl: z.string(),
  apiToken: z.string().optional(),
  apiTokenSet: z.boolean().optional(),
  elementWatts: finiteNumber("Element watts is required").min(0),
  electricityCostKwh: finiteNumber("Electricity cost is required").min(0),
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
