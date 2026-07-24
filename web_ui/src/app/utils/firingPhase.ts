import type { FiringStatus } from "../types/kiln";

/**
 * What the kiln is actually doing, as the UI needs to present it.
 *
 * The raw `status` string alone is not enough: the firmware reports
 * `is_active=true, status=IDLE` while a delayed start counts down, so a
 * dashboard keyed on `status` shows "Idle" for a kiln that is scheduled to fire
 * — and one keyed on `isActive` cannot tell a countdown from a live firing.
 */
export type FiringPhase =
  "idle" | "scheduled" | "running" | "paused" | "complete" | "error" | "autotune";

export function deriveFiringPhase(progress: {
  isActive: boolean;
  status: FiringStatus;
}): FiringPhase {
  const { isActive, status } = progress;

  // Terminal states are authoritative even if isActive hasn't cleared yet.
  if (status === "complete") return "complete";
  if (status === "error") return "error";
  if (status === "paused") return "paused";
  if (status === "autotune") return "autotune";

  // is_active with an IDLE status is the firmware's armed-delay state.
  if (status === "idle") return isActive ? "scheduled" : "idle";

  return isActive ? "running" : "idle";
}

/**
 * Whether elapsed time, segment and progress figures describe something real.
 *
 * Rendering them unconditionally left a stopped firing's numbers on screen next
 * to status "Idle" — and showed a segment name and "0h 0m remaining" for a
 * profile merely *selected* while idle, implying a firing that did not exist.
 */
export function showsFiringProgress(phase: FiringPhase): boolean {
  return phase === "running" || phase === "paused";
}
