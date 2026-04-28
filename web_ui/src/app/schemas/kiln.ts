import { z } from "zod";

export const firingSegmentSchema = z.object({
  id: z.string(),
  name: z.string().min(1, "Segment name is required"),
  rampRate: z.number({ message: "Ramp rate is required" }),
  targetTemp: z.number({ message: "Target temp is required" }).min(0).max(1400),
  holdTime: z.number({ message: "Hold time is required" }).min(0).max(65535),
});

export const profileFormSchema = z.object({
  name: z.string().min(1, "Profile name is required"),
  description: z.string(),
  segments: z.array(firingSegmentSchema).min(1, "At least one segment is required"),
});

export type ProfileFormValues = z.infer<typeof profileFormSchema>;

export const settingsSchema = z.object({
  tempUnit: z.enum(["C", "F"]),
  maxSafeTemp: z.number().min(0).max(1400),
  alarmEnabled: z.boolean(),
  autoShutdown: z.boolean(),
  notificationsEnabled: z.boolean(),
  tcOffsetC: z.number(),
  webhookUrl: z.string(),
  apiToken: z.string().optional(),
  apiTokenSet: z.boolean().optional(),
  elementWatts: z.number().min(0),
  electricityCostKwh: z.number().min(0),
});

export type SettingsFormValues = z.infer<typeof settingsSchema>;
