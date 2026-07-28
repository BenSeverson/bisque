import { describe, it, expect } from "vitest";
import {
  buildProfilePath,
  buildProfileTimeAxis,
  MAX_PROFILE_PATH_POINTS,
  MAX_PROFILE_AXIS_TICKS,
} from "./profilePath";
import { HOLD_UNTIL_SKIP, type FiringSegment } from "../types/kiln";

const seg = (over: Partial<FiringSegment>): FiringSegment => ({
  id: "s",
  name: "Segment",
  rampRate: 100,
  targetTemp: 600,
  holdTime: 0,
  ...over,
});

describe("buildProfilePath", () => {
  it("emits one point per 5 minutes of ramp for an ordinary profile", () => {
    // 20 -> 620 at 100°C/hr = 6h = 360 min => 72 steps, plus the origin point.
    const path = buildProfilePath([seg({ targetTemp: 620, rampRate: 100 })]);
    expect(path).toHaveLength(73);
    expect(path[0]).toEqual({ time: 0, temp: 20, target: 20 });
    expect(path[path.length - 1]).toEqual({ time: 360, temp: 620, target: 620 });
  });

  it("keeps a short segment legible with a floor on the step count", () => {
    // 20 -> 40 at 100°C/hr = 12 min: fewer than 10 five-minute steps.
    const path = buildProfilePath([seg({ targetTemp: 40, rampRate: 100 })]);
    expect(path).toHaveLength(11);
  });

  it("appends a point for a finite hold but not for hold-until-skip", () => {
    const held = buildProfilePath([seg({ targetTemp: 620, rampRate: 100, holdTime: 30 })]);
    expect(held[held.length - 1]).toEqual({ time: 390, temp: 620, target: 620 });

    const indefinite = buildProfilePath([
      seg({ targetTemp: 620, rampRate: 100, holdTime: HOLD_UNTIL_SKIP }),
    ]);
    expect(indefinite[indefinite.length - 1]).toEqual({ time: 360, temp: 620, target: 620 });
  });

  it("descends through a cooling segment", () => {
    const path = buildProfilePath([
      seg({ targetTemp: 1000, rampRate: 200 }),
      seg({ targetTemp: 800, rampRate: -100 }),
    ]);
    expect(path[path.length - 1].temp).toBe(800);
    expect(Math.max(...path.map((p) => p.temp))).toBe(1000);
  });

  it("bounds the point count for a near-zero ramp rate", () => {
    // The reported case (#160): 0.1°C/hr to 1300°C is a 780,000-minute ramp,
    // which at one point per 5 minutes is 156,000 points — enough to block the
    // main thread for a minute when Recharts renders it.
    const path = buildProfilePath([seg({ targetTemp: 1300, rampRate: 0.1 })]);
    expect(path.length).toBeLessThanOrEqual(MAX_PROFILE_PATH_POINTS + 2);
  });

  it("bounds the point count for an absurdly small ramp rate", () => {
    const path = buildProfilePath([seg({ targetTemp: 1300, rampRate: 0.0001 })]);
    expect(path.length).toBeLessThanOrEqual(MAX_PROFILE_PATH_POINTS + 2);
  });

  it("terminates on a zero ramp rate instead of looping forever", () => {
    // Not reachable through the form (the schema rejects it), but a profile
    // saved by an older build can still carry one, and Infinity/5 as a loop
    // bound never terminates.
    const path = buildProfilePath([seg({ targetTemp: 1300, rampRate: 0 })]);
    expect(path.length).toBeLessThanOrEqual(MAX_PROFILE_PATH_POINTS + 2);
  });

  it("stays bounded across the firmware's maximum segment count", () => {
    // FIRING_MAX_SEGMENTS is 16 (components/firing_engine/include/firing_types.h).
    const segments = Array.from({ length: 16 }, (_, i) =>
      seg({ id: `s${i}`, targetTemp: 100 + i, rampRate: 0.01, holdTime: 5 }),
    );
    const path = buildProfilePath(segments);
    expect(path.length).toBeLessThanOrEqual(MAX_PROFILE_PATH_POINTS + segments.length + 1);
  });

  it("returns nothing for an empty profile", () => {
    expect(buildProfilePath([])).toEqual([]);
  });
});

describe("buildProfileTimeAxis", () => {
  it("ticks every hour for a profile short enough to fit", () => {
    const path = buildProfilePath([seg({ targetTemp: 620, rampRate: 100 })]); // 6h
    expect(buildProfileTimeAxis(path)).toEqual({
      domainMax: 360,
      ticks: [0, 60, 120, 180, 240, 300, 360],
    });
  });

  it("rounds a partial hour up to the next whole hour", () => {
    const path = buildProfilePath([seg({ targetTemp: 320, rampRate: 100 })]); // 3h
    const axis = buildProfileTimeAxis(path);
    expect(axis.domainMax).toBe(180);
    expect(axis.ticks[axis.ticks.length - 1]).toBe(180);
  });

  it("widens the tick interval instead of emitting one tick per hour forever", () => {
    // 0.1°C/hr to 1300°C is a 13,000-hour profile: one tick per hour is 13,001
    // <text> nodes for Recharts to lay out, which blocks the main thread for
    // ~20s even with the path itself bounded.
    const path = buildProfilePath([seg({ targetTemp: 1300, rampRate: 0.1 })]);
    const axis = buildProfileTimeAxis(path);
    expect(axis.ticks.length).toBeLessThanOrEqual(MAX_PROFILE_AXIS_TICKS);
    expect(axis.ticks[0]).toBe(0);
    expect(axis.ticks[axis.ticks.length - 1]).toBe(axis.domainMax);
  });

  it("keeps ticks ascending, unique and inside the domain", () => {
    for (const rampRate of [200, 100, 12, 3, 1]) {
      const path = buildProfilePath([seg({ targetTemp: 1300, rampRate })]);
      const { domainMax, ticks } = buildProfileTimeAxis(path);
      expect(ticks.length).toBeLessThanOrEqual(MAX_PROFILE_AXIS_TICKS);
      expect(new Set(ticks).size).toBe(ticks.length);
      expect([...ticks].sort((a, b) => a - b)).toEqual(ticks);
      expect(Math.max(...ticks)).toBeLessThanOrEqual(domainMax);
    }
  });

  it("has no ticks for an empty path", () => {
    expect(buildProfileTimeAxis([])).toEqual({ domainMax: 0, ticks: [] });
  });
});
