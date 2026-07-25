import { describe, it, expect } from "vitest";
import { computeFiringProgress } from "./firingProgress";
import { HOLD_UNTIL_SKIP } from "../types/kiln";

const seg = (targetTemp: number, holdTime: number) => ({
  id: "s",
  name: "s",
  rampRate: 100,
  targetTemp,
  holdTime,
});

const finiteProfile = {
  estimatedDuration: 100, // minutes
  segments: [seg(500, 10), seg(1000, 10)],
};

const indefiniteProfile = {
  estimatedDuration: 60, // only the finite ramps
  segments: [seg(500, HOLD_UNTIL_SKIP), seg(1000, 0), seg(1100, 0), seg(1200, 0)],
};

describe("computeFiringProgress", () => {
  it("is time-based for an ordinary profile", () => {
    const r = computeFiringProgress({
      profile: finiteProfile,
      elapsedSeconds: 30 * 60,
      currentSegment: 0,
    });
    expect(r.timeBased).toBe(true);
    expect(r.percent).toBeCloseTo(30, 5);
  });

  it("clamps time-based progress at 100", () => {
    const r = computeFiringProgress({
      profile: finiteProfile,
      elapsedSeconds: 500 * 60,
      currentSegment: 1,
    });
    expect(r.percent).toBe(100);
  });

  it("never divides by a zero estimate", () => {
    // A profile that is nothing but an indefinite hold estimates to zero
    // minutes. elapsed / 0 is Infinity, which Math.min clamped to a confident
    // 100% one second into the firing.
    const holdOnly = { estimatedDuration: 0, segments: [seg(500, HOLD_UNTIL_SKIP)] };
    const r = computeFiringProgress({ profile: holdOnly, elapsedSeconds: 1, currentSegment: 0 });
    expect(Number.isFinite(r.percent)).toBe(true);
    expect(r.percent).toBeLessThan(100);
  });

  it("reports progress by segment when the profile holds indefinitely", () => {
    // Time cannot measure a profile whose length is unknowable: sitting in an
    // indefinite hold past the finite estimate would otherwise read 100% while
    // three segments had yet to run.
    const r = computeFiringProgress({
      profile: indefiniteProfile,
      elapsedSeconds: 999 * 60,
      currentSegment: 0,
    });
    expect(r.timeBased).toBe(false);
    expect(r.percent).toBe(0); // segment 0 of 4 complete
  });

  it("advances segment-based progress as segments complete", () => {
    const at = (i: number) =>
      computeFiringProgress({
        profile: indefiniteProfile,
        elapsedSeconds: 10 * 60,
        currentSegment: i,
      }).percent;
    expect(at(1)).toBe(25);
    expect(at(2)).toBe(50);
    expect(at(3)).toBe(75);
  });

  it("stays at zero before anything has elapsed", () => {
    const r = computeFiringProgress({
      profile: finiteProfile,
      elapsedSeconds: 0,
      currentSegment: 0,
    });
    expect(r.percent).toBe(0);
  });

  it("returns zero with no profile", () => {
    const r = computeFiringProgress({ profile: null, elapsedSeconds: 600, currentSegment: 0 });
    expect(r.percent).toBe(0);
  });
});
