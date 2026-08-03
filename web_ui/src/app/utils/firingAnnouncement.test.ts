import { describe, it, expect } from "vitest";
import { announcementFor, BASE_TAB_TITLE } from "./firingAnnouncement";
import type { FiringStatus } from "../types/kiln";

const ALL_STATUSES: FiringStatus[] = [
  "idle",
  "heating",
  "holding",
  "cooling",
  "complete",
  "error",
  "paused",
  "autotune",
];

const NON_TERMINAL = ALL_STATUSES.filter((s) => s !== "complete" && s !== "error");

describe("announcementFor", () => {
  it("announces every entry into complete", () => {
    for (const prev of ALL_STATUSES.filter((s) => s !== "complete")) {
      expect(announcementFor(prev, "complete")).toMatchObject({ kind: "complete" });
    }
  });

  it("announces every entry into error", () => {
    for (const prev of ALL_STATUSES.filter((s) => s !== "error")) {
      expect(announcementFor(prev, "error")).toMatchObject({ kind: "error" });
    }
  });

  // The firmware holds FIRING_STATUS_COMPLETE until the next start or stop, so
  // the seed from /api/v1/status can land on `complete` hours after the event.
  // With no baseline to compare against there is no transition to announce.
  it("stays silent with no prior observation, even landing on a terminal status", () => {
    for (const next of ALL_STATUSES) {
      expect(announcementFor(null, next)).toBeNull();
    }
  });

  it("stays silent while nothing has been observed at all", () => {
    expect(announcementFor(null, null)).toBeNull();
    for (const prev of ALL_STATUSES) {
      expect(announcementFor(prev, null)).toBeNull();
    }
  });

  it("stays silent while a terminal status persists across frames", () => {
    expect(announcementFor("complete", "complete")).toBeNull();
    expect(announcementFor("error", "error")).toBeNull();
  });

  it("stays silent for transitions into a non-terminal status", () => {
    for (const prev of ALL_STATUSES) {
      for (const next of NON_TERMINAL) {
        expect(announcementFor(prev, next)).toBeNull();
      }
    }
  });

  // A failure that arrives after a completion is its own event: the operator
  // saw "done", and needs to be told that reading no longer holds.
  it("announces error following complete, and complete following error", () => {
    expect(announcementFor("complete", "error")).toMatchObject({ kind: "error" });
    expect(announcementFor("error", "complete")).toMatchObject({ kind: "complete" });
  });

  it("carries non-empty copy and a tab title ending in the base title", () => {
    for (const next of ["complete", "error"] as const) {
      const a = announcementFor("heating", next);
      expect(a).not.toBeNull();
      expect(a!.title.length).toBeGreaterThan(0);
      expect(a!.body.length).toBeGreaterThan(0);
      expect(a!.tabTitle.endsWith(BASE_TAB_TITLE)).toBe(true);
      expect(a!.tabTitle).not.toBe(BASE_TAB_TITLE);
    }
  });
});

/**
 * The hook feeds this one status at a time, so the guarantees that matter are
 * about *sequences*, not single calls. `null` entries are renders where the
 * store has not yet observed the controller — its `firingProgress` still holds
 * the synthetic idle placeholder it was created with.
 */
function announceAll(sequence: (FiringStatus | null)[]): string[] {
  let prev: FiringStatus | null = null;
  const fired: string[] = [];
  for (const next of sequence) {
    const a = announcementFor(prev, next);
    if (a) fired.push(a.kind);
    prev = next;
  }
  return fired;
}

describe("as a sequence of observations", () => {
  it("announces once per firing that ends", () => {
    expect(
      announceAll([
        null,
        "idle",
        "heating",
        "heating",
        "holding",
        "cooling",
        "complete",
        "complete",
      ]),
    ).toEqual(["complete"]);
  });

  // The regression this shape exists for. The store starts at a synthetic
  // `idle`, and the firmware holds `complete` until the next start — so a page
  // opened the morning after a firing renders once with nothing observed, then
  // takes `complete` straight from the REST seed. Reading the placeholder as a
  // baseline turned that into idle→complete and re-announced a firing that
  // ended overnight, on every load, forever.
  it("stays silent when a reload lands on a firing that completed before it", () => {
    expect(announceAll([null, "complete", "complete", "complete"])).toEqual([]);
  });

  it("stays silent when a reload lands mid-failure", () => {
    expect(announceAll([null, "error", "error"])).toEqual([]);
  });

  // ...but the *next* firing is still announced, so the silence above is a
  // suppressed duplicate and not a permanently disarmed client.
  it("announces the next firing after a silent reload", () => {
    expect(announceAll([null, "complete", "heating", "cooling", "complete"])).toEqual(["complete"]);
  });

  it("announces a failure that follows a completion", () => {
    expect(announceAll([null, "idle", "heating", "complete", "heating", "error"])).toEqual([
      "complete",
      "error",
    ]);
  });

  it("does not re-announce when the controller drops out and returns unchanged", () => {
    expect(announceAll([null, "heating", "error", "error", "error"])).toEqual(["error"]);
  });
});
