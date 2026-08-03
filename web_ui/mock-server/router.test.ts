/**
 * Unit test for the transport-agnostic router (`dispatch`). The HTTP-level
 * parity test lives in handlers.test.ts; this one exercises dispatch() directly
 * — status codes, content types, and the download headers that the browser
 * demo relies on. The first block is deliberately timer-free (no firing or
 * autotune starts) so it leaves no open handles; the fault block below does
 * start firings and clears the interval it creates in afterEach.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { dispatch } from "./router";
import { state } from "./state";
import type { HistoryRecord } from "../src/app/types/kiln";

describe("dispatch() router", () => {
  it("GET /status returns a JSON body", () => {
    const r = dispatch("GET", "/status", {});
    expect(r.status).toBe(200);
    expect(r.json).toBeTruthy();
  });

  it("GET /cone-table returns a non-empty array", () => {
    const r = dispatch("GET", "/cone-table", {});
    expect(r.status).toBe(200);
    expect(Array.isArray(r.json)).toBe(true);
    expect((r.json as unknown[]).length).toBeGreaterThan(0);
  });

  it("GET /profiles/:id/export sets a download Content-Disposition header", () => {
    const list = dispatch("GET", "/profiles", {}).json as Array<{ id: string }>;
    const r = dispatch("GET", `/profiles/${list[0].id}/export`, {});
    expect(r.status).toBe(200);
    expect(r.contentType).toBe("application/json");
    expect(r.text).toContain(list[0].id);
    expect(r.headers?.["Content-Disposition"]).toContain(".json");
  });

  it("GET /history/:id/trace returns CSV text with the expected header", () => {
    const r = dispatch("GET", "/history/1/trace", {});
    expect(r.status).toBe(200);
    expect(r.contentType).toBe("text/csv");
    expect(r.text?.split("\n")[0]).toBe("time_s,temp_c");
  });

  it("POST /firing/start with an unknown profile returns 400 + ok:false", () => {
    const r = dispatch("POST", "/firing/start", { profileId: "does-not-exist" });
    expect(r.status).toBe(400);
    expect((r.json as { ok: boolean }).ok).toBe(false);
  });

  it("POST /settings persists and round-trips via GET /settings", () => {
    dispatch("POST", "/settings", { maxSafeTemp: 1234 });
    const after = dispatch("GET", "/settings", {}).json as { maxSafeTemp: number };
    expect(after.maxSafeTemp).toBe(1234);
  });

  it("unknown route returns 404", () => {
    const r = dispatch("GET", "/nope", {});
    expect(r.status).toBe(404);
  });
});

/**
 * The failure path, which had no way to be reached at all until #239 — every
 * seeded record was `errorCode: 0`, the simulator never entered `status:
 * "error"`, and /system hardcoded `emergencyStop: false`. So the error UI from
 * #235 was dead code in dev, in this suite, and in the published demo.
 *
 * These start real firings, so each one stops the ticker it created.
 */
describe("dispatch() fault simulation", () => {
  const profile = {
    id: "fault-test-profile",
    name: "Fault Test",
    description: "",
    segments: [{ id: "s1", name: "Ramp", rampRate: 100, targetTemp: 900, holdTime: 0 }],
    maxTemp: 900,
    estimatedDuration: 540,
  };

  beforeEach(() => {
    dispatch("POST", "/profiles", profile);
  });

  afterEach(() => {
    dispatch("POST", "/firing/stop", {});
    dispatch("DELETE", `/profiles/${profile.id}`, {});
    // Clear the latch so the next test starts from a healthy kiln, and drop the
    // interval the trip's cool-down left running.
    state.emergencyStop = false;
    state.lastErrorCode = 0;
    state.firing.status = "idle";
    if (state.interval) {
      clearInterval(state.interval);
      state.interval = null;
    }
  });

  it("seeds a history record with a real error code", () => {
    const history = dispatch("GET", "/history", {}).json as HistoryRecord[];
    const failed = history.filter((r) => r.outcome === "error");
    expect(failed.length).toBeGreaterThan(0);
    expect(failed[0].errorCode).toBeGreaterThan(0);
  });

  it("lists history newest first, the order history_get_records() returns", () => {
    const history = dispatch("GET", "/history", {}).json as HistoryRecord[];
    const times = history.map((r) => r.startTime);
    expect(times).toEqual([...times].sort((a, b) => b - a));
  });

  it("a fault mid-firing lands in status error with a non-zero lastErrorCode", () => {
    dispatch("POST", "/firing/start", { profileId: profile.id });
    const r = dispatch("POST", "/mock/fault", { code: 3 });
    expect(r.status).toBe(200);

    const status = dispatch("GET", "/status", {}).json as { status: string; isActive: boolean };
    expect(status.status).toBe("error");
    // The firmware drops is_active on the trip; the dashboard banner reads both.
    expect(status.isActive).toBe(false);

    const system = dispatch("GET", "/system", {}).json as {
      emergencyStop: boolean;
      lastErrorCode: number;
    };
    expect(system.emergencyStop).toBe(true);
    expect(system.lastErrorCode).toBe(3);
  });

  it("records the failed firing in history with its cause", () => {
    const before = (dispatch("GET", "/history", {}).json as HistoryRecord[]).length;
    dispatch("POST", "/firing/start", { profileId: profile.id });
    dispatch("POST", "/mock/fault", { code: 1 });

    const history = dispatch("GET", "/history", {}).json as HistoryRecord[];
    expect(history.length).toBe(before + 1);
    expect(history[0].outcome).toBe("error");
    expect(history[0].errorCode).toBe(1);
    expect(history[0].profileId).toBe(profile.id);
  });

  it("a fault while idle latches the flag without recording a cause", () => {
    // s_last_error_code is only ever assigned inside the firing loop, so a trip
    // with nothing running leaves the bare flag — the one case where "start a
    // firing to clear it" is the whole truth.
    dispatch("POST", "/mock/fault", { code: 2 });
    const system = dispatch("GET", "/system", {}).json as {
      emergencyStop: boolean;
      lastErrorCode: number;
    };
    expect(system.emergencyStop).toBe(true);
    expect(system.lastErrorCode).toBe(0);
    expect((dispatch("GET", "/status", {}).json as { status: string }).status).toBe("idle");
  });

  it("starting a firing clears the latched stop, as safety_clear_emergency() does", () => {
    dispatch("POST", "/firing/start", { profileId: profile.id });
    dispatch("POST", "/mock/fault", { code: 4 });
    expect((dispatch("GET", "/system", {}).json as { emergencyStop: boolean }).emergencyStop).toBe(
      true,
    );

    dispatch("POST", "/firing/start", { profileId: profile.id });
    const system = dispatch("GET", "/system", {}).json as {
      emergencyStop: boolean;
      lastErrorCode: number;
    };
    expect(system.emergencyStop).toBe(false);
    expect(system.lastErrorCode).toBe(0);
  });

  it("rejects a non-positive fault code", () => {
    expect(dispatch("POST", "/mock/fault", { code: 0 }).status).toBe(400);
    expect(dispatch("POST", "/mock/fault", { code: -1 }).status).toBe(400);
  });

  it("records a stopped firing as aborted, like history_firing_end()", () => {
    const before = (dispatch("GET", "/history", {}).json as HistoryRecord[]).length;
    dispatch("POST", "/firing/start", { profileId: profile.id });
    dispatch("POST", "/firing/stop", {});

    const history = dispatch("GET", "/history", {}).json as HistoryRecord[];
    expect(history.length).toBe(before + 1);
    expect(history[0].outcome).toBe("aborted");
    expect(history[0].errorCode).toBe(0);
  });

  it("does not record an armed delayed start that never began firing", () => {
    // history_firing_start() runs in begin_firing(), so nothing is open during
    // the countdown and history_firing_end() returns early.
    const before = (dispatch("GET", "/history", {}).json as HistoryRecord[]).length;
    dispatch("POST", "/firing/start", { profileId: profile.id, delayMinutes: 30 });
    dispatch("POST", "/firing/stop", {});
    expect((dispatch("GET", "/history", {}).json as HistoryRecord[]).length).toBe(before);
  });
});
