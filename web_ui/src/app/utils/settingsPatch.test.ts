import { describe, it, expect } from "vitest";
import { prepareSettingsPatch } from "./settingsPatch";
import { SettingsFormValues } from "../schemas/kiln";

const valid: SettingsFormValues = {
  tempUnit: "F",
  maxSafeTemp: 1200,
  alarmEnabled: true,
  autoShutdown: false,
  notificationsEnabled: true,
  tcOffsetC: 0,
  webhookUrl: "",
  elementWatts: 2400,
  electricityCostKwh: 0.15,
};

describe("prepareSettingsPatch", () => {
  it("merges the changed field into the payload when the form is valid", () => {
    const result = prepareSettingsPatch(valid, "alarmEnabled", false);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.settings.alarmEnabled).toBe(false);
    expect(result.settings.maxSafeTemp).toBe(1200);
  });

  it("carries the API token fields through untouched", () => {
    const result = prepareSettingsPatch(
      { ...valid, apiTokenSet: true, apiToken: "secret" },
      "autoShutdown",
      true,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.settings.apiTokenSet).toBe(true);
    expect(result.settings.apiToken).toBe("secret");
  });

  it("refuses to save a mid-edit empty temperature field instead of sending 0", () => {
    // TemperatureField yields NaN for an empty input; JSON.stringify turns that
    // into null and the firmware's (float)valuedouble reads it as 0.0, so
    // max_safe_temp became 0 and validate_profile() then rejected every firing.
    const result = prepareSettingsPatch({ ...valid, maxSafeTemp: NaN }, "alarmEnabled", true);
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.message).toMatch(/max safe temperature/i);
  });

  it("refuses an empty thermocouple offset too", () => {
    const result = prepareSettingsPatch({ ...valid, tcOffsetC: NaN }, "tempUnit", "C");
    expect(result.ok).toBe(false);
  });

  it("refuses an out-of-range safe temperature", () => {
    const result = prepareSettingsPatch({ ...valid, maxSafeTemp: 2000 }, "alarmEnabled", true);
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.message.length).toBeGreaterThan(0);
  });

  it("validates the incoming value itself, not just the rest of the form", () => {
    const result = prepareSettingsPatch(valid, "maxSafeTemp", NaN);
    expect(result.ok).toBe(false);
  });

  it("refuses a form snapshot that is missing fields entirely", () => {
    const result = prepareSettingsPatch({}, "alarmEnabled", true);
    expect(result.ok).toBe(false);
  });
});
