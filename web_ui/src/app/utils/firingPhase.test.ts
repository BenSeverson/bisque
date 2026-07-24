import { describe, it, expect } from "vitest";
import { deriveFiringPhase, showsFiringProgress } from "./firingPhase";

describe("deriveFiringPhase", () => {
  it("reports a running firing for each active status", () => {
    for (const status of ["heating", "holding", "cooling"] as const) {
      expect(deriveFiringPhase({ isActive: true, status })).toBe("running");
    }
  });

  it("distinguishes an armed delayed start from a genuinely idle kiln", () => {
    // The firmware reports is_active=true with status=IDLE while a delay counts
    // down. Treating that as plain "idle" made the dashboard look as though
    // nothing had been scheduled at all.
    expect(deriveFiringPhase({ isActive: true, status: "idle" })).toBe("scheduled");
    expect(deriveFiringPhase({ isActive: false, status: "idle" })).toBe("idle");
  });

  it("reports paused, complete, error and autotune distinctly", () => {
    expect(deriveFiringPhase({ isActive: true, status: "paused" })).toBe("paused");
    expect(deriveFiringPhase({ isActive: false, status: "complete" })).toBe("complete");
    expect(deriveFiringPhase({ isActive: false, status: "error" })).toBe("error");
    expect(deriveFiringPhase({ isActive: true, status: "autotune" })).toBe("autotune");
  });

  it("trusts the status over a stale isActive for terminal states", () => {
    // A complete/error frame may still carry isActive=true briefly; the status
    // is the authority for those.
    expect(deriveFiringPhase({ isActive: true, status: "complete" })).toBe("complete");
    expect(deriveFiringPhase({ isActive: true, status: "error" })).toBe("error");
  });
});

describe("showsFiringProgress", () => {
  it("shows progress only while a firing is actually under way", () => {
    expect(showsFiringProgress("running")).toBe(true);
    expect(showsFiringProgress("paused")).toBe(true);
  });

  it("hides progress when there is no firing in flight", () => {
    // Leaving elapsed/segment/ETA on screen after a stop showed a dead
    // firing's numbers next to status "Idle".
    for (const phase of ["idle", "scheduled", "complete", "error"] as const) {
      expect(showsFiringProgress(phase)).toBe(false);
    }
  });
});
