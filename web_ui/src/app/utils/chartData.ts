import type { TemperatureDataPoint } from "../types/kiln";
import { toDisplayTemp, type TempUnit } from "./temperature";

export interface ChartPoint {
  time: number;
  profile?: number;
  current?: number;
  target?: number;
}

/**
 * Merge the live temperature series with the planned profile path, in the
 * user's display unit.
 *
 * Conversion is applied on every path through this function. Previously the
 * no-profile case returned the raw Celsius series while the profile case
 * converted, so with °F selected and no profile chosen the chart plotted
 * Celsius values against an axis labelled °F — contradicting the status cards
 * on the same screen.
 */
export function buildChartData(args: {
  currentTempData: TemperatureDataPoint[];
  profilePath: TemperatureDataPoint[];
  unit: TempUnit;
}): ChartPoint[] {
  const { currentTempData, profilePath, unit } = args;
  const conv = (c: number) => Math.round(toDisplayTemp(c, unit));

  const map = new Map<number, ChartPoint>();

  profilePath.forEach((point) => {
    map.set(point.time, { time: point.time, profile: conv(point.temp) });
  });

  currentTempData.forEach((point) => {
    const existing = map.get(point.time);
    if (existing) {
      existing.current = conv(point.temp);
      existing.target = conv(point.target);
    } else {
      map.set(point.time, {
        time: point.time,
        current: conv(point.temp),
        target: conv(point.target),
      });
    }
  });

  return Array.from(map.values()).sort((a, b) => a.time - b.time);
}
