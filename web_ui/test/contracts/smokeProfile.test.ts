/**
 * Validates docs/smoke-test-profile.json against firingProfileSchema. If the
 * profile schema or the bench checklist drift, this test catches it before
 * an operator types in a no-longer-valid profile on the bench.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";
import { firingProfileSchema } from "../../src/app/schemas/kiln";

describe("docs/smoke-test-profile.json", () => {
  const profile = JSON.parse(
    readFileSync(join(__dirname, "../../../docs/smoke-test-profile.json"), "utf8"),
  );

  it("parses against firingProfileSchema", () => {
    expect(firingProfileSchema.parse(profile)).toBeDefined();
  });

  it("stays well under any reasonable max_safe_temp", () => {
    // The firmware's validate_profile() rejects profiles whose max_temp
    // exceeds the safety limit. The smoke test only peaks at 50°C — anything
    // higher in this file means someone misedited the smoke profile.
    expect(profile.maxTemp).toBeLessThanOrEqual(80);
    for (const seg of profile.segments) {
      expect(seg.targetTemp).toBeLessThanOrEqual(80);
    }
  });
});
