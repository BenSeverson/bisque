import { describe, it, expect } from "vitest";
import { buildChartData } from "./chartData";
import type { TemperatureDataPoint } from "../types/kiln";

const live: TemperatureDataPoint[] = [
  { time: 0, temp: 20, target: 20 },
  { time: 1, temp: 1000, target: 1010 },
];

const path: TemperatureDataPoint[] = [
  { time: 0, temp: 20, target: 20 },
  { time: 1, temp: 1005, target: 1005 },
];

describe("buildChartData", () => {
  it("converts live temperatures to the display unit when no profile is selected", () => {
    // The no-profile branch used to pass Celsius through raw while the axis
    // stayed labelled °F, so a kiln at 1000°C plotted as "1000" on a °F axis
    // while the status card above it read 1832°F.
    const data = buildChartData({ currentTempData: live, profilePath: [], unit: "F" });
    const hot = data.find((p) => p.time === 1)!;
    expect(hot.current).toBe(1832);
    expect(hot.target).toBe(1850);
  });

  it("leaves values in Celsius when that is the display unit", () => {
    const data = buildChartData({ currentTempData: live, profilePath: [], unit: "C" });
    expect(data.find((p) => p.time === 1)!.current).toBe(1000);
  });

  it("converts identically whether or not a profile is selected", () => {
    // The two branches diverging is the actual defect; pin them together.
    const without = buildChartData({ currentTempData: live, profilePath: [], unit: "F" });
    const with_ = buildChartData({ currentTempData: live, profilePath: path, unit: "F" });
    for (const t of [0, 1]) {
      expect(with_.find((p) => p.time === t)!.current).toBe(
        without.find((p) => p.time === t)!.current,
      );
    }
  });

  it("merges the profile path and converts it too", () => {
    const data = buildChartData({ currentTempData: live, profilePath: path, unit: "F" });
    const hot = data.find((p) => p.time === 1)!;
    expect(hot.profile).toBe(1841);
    expect(hot.current).toBe(1832);
  });

  it("returns points sorted by time", () => {
    const scrambled: TemperatureDataPoint[] = [
      { time: 5, temp: 100, target: 100 },
      { time: 2, temp: 50, target: 50 },
    ];
    const data = buildChartData({ currentTempData: scrambled, profilePath: path, unit: "C" });
    expect(data.map((p) => p.time)).toEqual([...data.map((p) => p.time)].sort((a, b) => a - b));
  });
});
