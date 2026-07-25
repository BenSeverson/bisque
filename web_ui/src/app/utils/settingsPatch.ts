import { settingsSchema, SettingsFormValues } from "../schemas/kiln";

export type SettingsPatchResult =
  { ok: true; settings: SettingsFormValues } | { ok: false; message: string };

/**
 * Validate the whole settings form before an immediate-save control (a switch
 * or a select) persists it.
 *
 * Those controls bypass `handleSubmit`, so they used to POST `getValues()`
 * unvalidated. A `TemperatureField` the user had cleared mid-edit holds NaN,
 * which `JSON.stringify` writes as `null` and the firmware's
 * `(float)j->valuedouble` reads back as `0.0` — so flipping an unrelated switch
 * while "Maximum Safe Temperature" was empty stored `max_safe_temp = 0`, after
 * which `validate_profile()` rejected every firing start (issue #126).
 *
 * Gating on `settingsSchema` rather than an ad-hoc isfinite check keeps one
 * definition of "valid settings": the same schema the form's resolver uses on
 * explicit submit, so an immediate save can never persist something the Save
 * button would have refused. It also catches the neighbouring cases for free
 * (out-of-range limits, a missing field) without a second list of rules.
 *
 * The caller should apply the new value only when this returns ok, so a
 * refused toggle springs back instead of showing a state the device never took.
 */
export function prepareSettingsPatch<K extends keyof SettingsFormValues>(
  values: unknown,
  field: K,
  value: SettingsFormValues[K],
): SettingsPatchResult {
  const candidate = { ...(values as object), [field]: value };
  const parsed = settingsSchema.safeParse(candidate);
  if (parsed.success) return { ok: true, settings: parsed.data };
  // settingsSchema carries a field-naming message on every rule, so the first
  // issue reads as a complete sentence in a toast.
  return { ok: false, message: parsed.error.issues[0]?.message ?? "Settings are invalid" };
}
