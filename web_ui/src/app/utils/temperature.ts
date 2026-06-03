// Temperature unit conversion for display. All temperatures are stored and
// exchanged with the controller in Celsius (the canonical unit); these helpers
// convert to the user's chosen display unit only at the presentation boundary.
//
// Absolute temperatures use the full affine conversion (×9/5 + 32). Deltas/rates
// — ramp rate (°C/hr), thermocouple offset — are differences, so they scale by
// 9/5 with no +32 offset.

export type TempUnit = "C" | "F";

/** Convert a Celsius temperature to the display unit. */
export function toDisplayTemp(celsius: number, unit: TempUnit): number {
  return unit === "F" ? celsius * (9 / 5) + 32 : celsius;
}

/** Convert a display-unit temperature back to Celsius. */
export function fromDisplayTemp(value: number, unit: TempUnit): number {
  return unit === "F" ? (value - 32) * (5 / 9) : value;
}

/** Convert a Celsius delta/rate (e.g. °C/hr) to the display unit (scale only). */
export function toDisplayRate(celsius: number, unit: TempUnit): number {
  return unit === "F" ? celsius * (9 / 5) : celsius;
}

/** Convert a display-unit delta/rate back to Celsius (scale only). */
export function fromDisplayRate(value: number, unit: TempUnit): number {
  return unit === "F" ? value * (5 / 9) : value;
}

/** Unit suffix for an absolute temperature, e.g. "°F". */
export function unitLabel(unit: TempUnit): string {
  return unit === "F" ? "°F" : "°C";
}

/** Unit suffix for a ramp rate, e.g. "°F/hr". */
export function rateLabel(unit: TempUnit): string {
  return unit === "F" ? "°F/hr" : "°C/hr";
}

/** Format a Celsius temperature in the display unit, rounded, with suffix. */
export function formatTemp(celsius: number, unit: TempUnit, digits = 0): string {
  return `${toDisplayTemp(celsius, unit).toFixed(digits)}${unitLabel(unit)}`;
}

/** Format a Celsius/hr ramp rate in the display unit, rounded, with suffix. */
export function formatRate(celsius: number, unit: TempUnit, digits = 0): string {
  return `${toDisplayRate(celsius, unit).toFixed(digits)}${rateLabel(unit)}`;
}
