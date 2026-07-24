import { describe, it, expect } from "vitest";
import { computeSegmentDurationMinutes, makeDuplicateProfileId } from "./profile";

describe("computeSegmentDurationMinutes", () => {
  it("computes ramp time from temp difference and rate", () => {
    // 100→300°C at 200°C/hr = 1h = 60m
    const r = computeSegmentDurationMinutes(
      { targetTemp: 300, rampRate: 200, holdMinutes: 0 },
      100,
    );
    expect(r.rampMinutes).toBeCloseTo(60, 5);
    expect(r.holdMinutes).toBe(0);
  });

  it("passes hold time through unchanged", () => {
    const r = computeSegmentDurationMinutes(
      { targetTemp: 500, rampRate: 100, holdMinutes: 30 },
      100,
    );
    expect(r.holdMinutes).toBe(30);
  });

  it("treats descending ramps as positive duration", () => {
    // Cooling segment: 800→500°C at -100°C/hr should still be 3h = 180m
    const r = computeSegmentDurationMinutes(
      { targetTemp: 500, rampRate: -100, holdMinutes: 0 },
      800,
    );
    expect(r.rampMinutes).toBeCloseTo(180, 5);
  });

  it("returns zero ramp when target equals current temp", () => {
    const r = computeSegmentDurationMinutes({ targetTemp: 100, rampRate: 60, holdMinutes: 5 }, 100);
    expect(r.rampMinutes).toBe(0);
    expect(r.holdMinutes).toBe(5);
  });
});

/* Mirrors the firmware's make_nvs_key(): first 15 chars of the id, with
   anything outside [A-Za-z0-9_] replaced by '_'. Two profiles whose ids reduce
   to the same key are rejected by the firmware with a 409. */
function nvsKey(id: string): string {
  return id.slice(0, 15).replace(/[^A-Za-z0-9_]/g, "_");
}

describe("makeDuplicateProfileId", () => {
  const sources = [
    "cone-04-Medium", // cone-fire profile
    "bisque-04", // short built-in id
    "3f2a5c81-9d4e-4b7a-8c16-2e5f9a0d7b34", // ProfileBuilder UUID
    "verylongprofileid-with-a-tail",
  ];

  it.each(sources)("differs from %s within the firmware's 15-char NVS key", (source) => {
    const copy = makeDuplicateProfileId(source);
    expect(nvsKey(copy)).not.toBe(nvsKey(source));
  });

  it("gives distinct keys for repeated duplicates of the same profile", () => {
    const source = "cone-04-Medium";
    const keys = new Set(Array.from({ length: 25 }, () => nvsKey(makeDuplicateProfileId(source))));
    expect(keys.size).toBe(25);
  });

  it("keeps the id within the firmware's 40-char field", () => {
    for (const source of sources) {
      expect(makeDuplicateProfileId(source).length).toBeLessThanOrEqual(39);
    }
  });
});
