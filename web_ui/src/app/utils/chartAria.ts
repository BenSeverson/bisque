/**
 * Accessible descriptions for the two temperature charts.
 *
 * Recharts renders a bare `<svg>` of `<path>` elements with no accessible name,
 * so a screen reader announces nothing at all where a sighted user sees the
 * entire firing (#170). Wrapping the chart in `role="img"` plus one of these
 * labels is the standard remedy: the graphic is presented as a single image
 * whose alt text carries the information the shape conveys.
 *
 * The labels state the range and the endpoints rather than reading out every
 * point — a 500-point trace read aloud is worse than no chart at all.
 */

import { formatTemp, type TempUnit } from "./temperature";

/**
 * Live dashboard chart: planned path plus the temperatures recorded so far.
 *
 * Takes the raw Celsius series, not the assembled `ChartPoint[]` — those are
 * already converted to the display unit by `buildChartData`, and passing them
 * to `formatTemp` (which converts from Celsius) would convert twice.
 */
export function describeFiringChart(args: {
  points: { temp: number }[];
  hasPlanned: boolean;
  unit: TempUnit;
}): string {
  const temps = args.points
    .map((p) => p.temp)
    .filter((t): t is number => typeof t === "number" && Number.isFinite(t));

  const planned = args.hasPlanned ? " against the planned profile" : "";

  if (temps.length === 0) {
    return args.hasPlanned
      ? "Temperature chart showing the planned profile. No temperatures recorded yet."
      : "Temperature chart. No data yet.";
  }

  const latest = temps[temps.length - 1];
  const peak = Math.max(...temps);
  return (
    `Temperature chart${planned}. ${temps.length} reading${temps.length === 1 ? "" : "s"}, ` +
    `currently ${formatTemp(latest, args.unit)}, peak ${formatTemp(peak, args.unit)}.`
  );
}

/** History detail chart: the recorded trace of one completed firing. */
export function describeTraceChart(args: {
  points: { temp_c: number; time_s: number }[];
  profileName: string;
  unit: TempUnit;
}): string {
  if (args.points.length === 0) {
    return `Temperature trace for ${args.profileName}. No trace data recorded.`;
  }
  const temps = args.points.map((p) => p.temp_c);
  const peak = Math.max(...temps);
  const durationMin = Math.round(args.points[args.points.length - 1].time_s / 60);
  return (
    `Temperature trace for ${args.profileName}. ${args.points.length} readings over ` +
    `${durationMin} minute${durationMin === 1 ? "" : "s"}, peak ${formatTemp(peak, args.unit)}.`
  );
}
