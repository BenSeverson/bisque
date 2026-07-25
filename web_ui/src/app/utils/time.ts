/** Format seconds as "Xh Ym" */
export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

/** Format minutes as "Xh Ym" */
export function formatDurationFromMinutes(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.floor(minutes % 60);
  return `${h}h ${m}m`;
}

/**
 * Format a countdown, dropping units that would read as noise.
 *
 * Unlike formatDuration this never shows "0h" — an 8-hour overnight delay wants
 * "7h 58m" but the last minute wants "42s", not "0h 0m". Used for the scheduled
 * firing countdown (#204).
 */
export function formatCountdown(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

/** Format seconds as "Xh Ym Zs" */
export function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}h ${m}m ${s}s`;
}
