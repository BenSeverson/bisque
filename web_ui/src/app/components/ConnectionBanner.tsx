import { useEffect, useState } from "react";
import { WifiOff, AlertTriangle } from "lucide-react";
import { useKilnStore } from "../stores/kilnStore";
import { deriveConnectionHealth } from "../utils/connectionHealth";

/**
 * Warns when the readings on screen may no longer reflect the kiln.
 *
 * Without this, a device that reboots or drops off Wi-Fi mid-firing leaves its
 * last temperature and status on the dashboard indefinitely, visually identical
 * to a healthy connection — the operator has no way to tell that a firing has
 * since errored or completed.
 */
export function ConnectionBanner() {
  const connectionState = useKilnStore((s) => s.connectionState);
  const lastUpdateAt = useKilnStore((s) => s.lastUpdateAt);

  // Staleness is a function of elapsed time, so re-evaluate on a timer rather
  // than only when a frame arrives — the whole point is detecting the absence
  // of frames.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const { health, msSinceUpdate } = deriveConnectionHealth({
    state: connectionState,
    lastUpdateAt,
    now,
  });

  if (health === "live") return null;

  const offline = health === "offline";
  const seconds = msSinceUpdate === null ? null : Math.floor(msSinceUpdate / 1000);

  return (
    <div
      role="status"
      aria-live="polite"
      className={
        offline
          ? "flex items-center gap-3 rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-destructive"
          : "flex items-center gap-3 rounded-md border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-amber-700 dark:text-amber-400"
      }
    >
      {offline ? (
        <WifiOff className="h-5 w-5 shrink-0" aria-hidden="true" />
      ) : (
        <AlertTriangle className="h-5 w-5 shrink-0" aria-hidden="true" />
      )}
      <div className="text-sm">
        <p className="font-medium">
          {offline
            ? connectionState === "connecting"
              ? "Reconnecting to kiln…"
              : "Not connected to kiln"
            : "No recent updates from kiln"}
        </p>
        <p className="opacity-90">
          {seconds === null
            ? "Readings below are not live."
            : `Readings below are ${seconds}s old and may not reflect the kiln.`}
        </p>
      </div>
    </div>
  );
}
