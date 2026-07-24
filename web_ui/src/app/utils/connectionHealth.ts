import type { WSConnectionState } from "../services/websocket";

/**
 * How long an open socket may go without a telemetry frame before the readings
 * on screen are treated as stale.
 *
 * The controller broadcasts continuously while powered, so silence on an open
 * socket means the numbers no longer reflect the kiln — the socket staying open
 * is not by itself evidence that the data is current.
 */
export const STALE_AFTER_MS = 10_000;

export type ConnectionHealth = "live" | "stale" | "offline";

export interface ConnectionHealthResult {
  health: ConnectionHealth;
  /** Age of the most recent telemetry frame, or null if none has arrived. */
  msSinceUpdate: number | null;
}

/**
 * Classify how much the dashboard's readings can be trusted.
 *
 * Without this the UI cannot distinguish a healthy connection from a device
 * that rebooted or dropped off Wi-Fi mid-firing: the last received temperature
 * and status simply stay on screen indefinitely, looking live.
 */
export function deriveConnectionHealth(args: {
  state: WSConnectionState;
  lastUpdateAt: number | null;
  now: number;
}): ConnectionHealthResult {
  const { state, lastUpdateAt, now } = args;

  // Clamp: a device clock slightly ahead of the browser's shouldn't read as a
  // negative age.
  const msSinceUpdate = lastUpdateAt === null ? null : Math.max(0, now - lastUpdateAt);

  if (state !== "open") {
    return { health: "offline", msSinceUpdate };
  }
  if (msSinceUpdate === null || msSinceUpdate > STALE_AFTER_MS) {
    return { health: "stale", msSinceUpdate };
  }
  return { health: "live", msSinceUpdate };
}
