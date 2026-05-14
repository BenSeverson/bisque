import { describe, it, expect } from "vitest";
import { computeSegmentDurationMinutes } from "./profile";

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
