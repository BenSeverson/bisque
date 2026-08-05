/**
 * Unit test for the transport-agnostic router (`dispatch`). The HTTP-level
 * parity test lives in handlers.test.ts; this one exercises dispatch() directly
 * — status codes, content types, and the download headers that the browser
 * demo relies on. The first block is deliberately timer-free (no firing or
 * autotune starts) so it leaves no open handles; the fault block below does
 * start firings and clears the interval it creates in afterEach.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
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

  it("POST /firing/start with an unknown profile returns 400 + a plain-text message", () => {
    const r = dispatch("POST", "/firing/start", { profileId: "does-not-exist" });
    expect(r.status).toBe(400);
    // The firmware's own wording, sent as the body with no JSON envelope
    // around it — see api_handlers.c and apiError() in router.ts (#174).
    expect(r.text).toBe("Profile not found");
    expect(r.json).toBeUndefined();
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
    state.autotune.running = false;
    state.autotune.completed = false;
    if (state.autotune.interval) {
      clearInterval(state.autotune.interval);
      state.autotune.interval = null;
    }
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

  it("treats a running auto-tune as active, like s_progress.is_active", () => {
    // FIRING_CMD_AUTOTUNE_START raises is_active, so the emergency branch in
    // firing_loop() applies to a tune exactly as it does to a firing.
    dispatch("POST", "/autotune/start", { setpoint: 200, hysteresis: 5 });
    dispatch("POST", "/mock/fault", { code: 2 });

    expect((dispatch("GET", "/status", {}).json as { status: string }).status).toBe("error");
    expect((dispatch("GET", "/system", {}).json as { lastErrorCode: number }).lastErrorCode).toBe(
      2,
    );
    // The tune must actually stop: its interval would otherwise keep heating
    // and rewrite the status to "autotune" a second later.
    expect((dispatch("GET", "/autotune/status", {}).json as { state: string }).state).not.toBe(
      "running",
    );
    expect(state.autotune.interval).toBeNull();
  });

  it("writes no history record for a faulted auto-tune", () => {
    // history_firing_start() runs only in begin_firing(), so history_firing_end()
    // returns early on !s_recording.
    const before = (dispatch("GET", "/history", {}).json as HistoryRecord[]).length;
    dispatch("POST", "/autotune/start", { setpoint: 200, hysteresis: 5 });
    dispatch("POST", "/mock/fault", { code: 1 });
    expect((dispatch("GET", "/history", {}).json as HistoryRecord[]).length).toBe(before);
  });

  it("serves a header-only trace for a firing shorter than one sample", () => {
    // history_record_temp() samples once a minute. `i / steps` used to be 0/0
    // here, emitting a literal `0,NaN` row into the downloaded CSV.
    dispatch("POST", "/firing/start", { profileId: profile.id });
    dispatch("POST", "/firing/stop", {});
    const record = (dispatch("GET", "/history", {}).json as HistoryRecord[])[0];
    expect(record.durationS).toBeLessThan(60);

    const csv = dispatch("GET", `/history/${record.id}/trace`, {}).text ?? "";
    expect(csv).toBe("time_s,temp_c");
    expect(csv).not.toContain("NaN");
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

/**
 * Natural completion, driven through the real 1 Hz ticker on fake timers.
 *
 * Both assertions here are about ordering inside tick(). The record used to be
 * written from advanceSegment(), one statement before the tick's own
 * updateTemperature() — so it missed the final reading — and the status
 * "complete" that advanceSegment() set was then overwritten by
 * determineStatus(), which answers "idle" for anything not running.
 */
describe("dispatch() natural completion", () => {
  const profile = {
    id: "completion-test-profile",
    name: "Completion Test",
    description: "",
    segments: [{ id: "s1", name: "Ramp", rampRate: 200, targetTemp: 400, holdTime: 0 }],
    maxTemp: 400,
    estimatedDuration: 120,
  };

  beforeEach(() => {
    vi.useFakeTimers();
    dispatch("POST", "/profiles", profile);
  });

  afterEach(() => {
    dispatch("POST", "/firing/stop", {});
    dispatch("DELETE", `/profiles/${profile.id}`, {});
    if (state.interval) {
      clearInterval(state.interval);
      state.interval = null;
    }
    vi.useRealTimers();
    state.firing.status = "idle";
    state.firing.coolingDown = false;
    state.firing.currentTemp = 20;
  });

  it("holds the complete status and records the final tick's peak", () => {
    dispatch("POST", "/firing/start", { profileId: profile.id });

    // 200°C/hr from ambient to 400°C is ~6840 simulated seconds; at 60x that is
    // 114 ticks. Advance generously, then stop as soon as it lands.
    for (let i = 0; i < 400 && state.firing.running; i++) {
      vi.advanceTimersByTime(1000);
    }
    expect(state.firing.running).toBe(false);

    // determineStatus() must not get the last word here.
    expect((dispatch("GET", "/status", {}).json as { status: string }).status).toBe("complete");

    const record = (dispatch("GET", "/history", {}).json as HistoryRecord[])[0];
    expect(record.outcome).toBe("complete");
    expect(record.errorCode).toBe(0);
    // Written after the tick folded in its reading, so it carries the same peak
    // the simulator ended on rather than the previous tick's.
    expect(record.peakTemp).toBe(Math.round(state.firing.peakTemp));
  });
});

/**
 * The tune runs on its own interval with state.firing.running still false, so
 * a duty derived from the firing state alone reads a flat 0% for the whole run
 * (#180 review). The firmware drives the SSR bang-bang on every tune tick, and
 * watching the element cycle is the reason to look at the card during a tune.
 */
describe("dispatch() auto-tune element power", () => {
  const dutyOf = () => (dispatch("GET", "/status", {}).json as { dutyPercent: number }).dutyPercent;

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    dispatch("POST", "/autotune/stop", {});
    if (state.interval) {
      clearInterval(state.interval);
      state.interval = null;
    }
    vi.useRealTimers();
    state.firing.status = "idle";
    state.firing.coolingDown = false;
    state.firing.currentTemp = 20;
  });

  it("cycles the relay across a tune rather than sitting at zero", () => {
    dispatch("POST", "/autotune/start", { setpoint: 900, hysteresis: 5 });

    // The tune ends itself at 60 ticks, which is a shade under one full
    // oscillation (0.1 rad/tick) — enough for one trough and one peak.
    const seen = new Set<number>();
    for (let i = 0; i < 60 && state.autotune.running; i++) {
      vi.advanceTimersByTime(1000);
      if (state.autotune.running) seen.add(dutyOf());
    }
    expect([...seen].sort()).toEqual([0, 100]);
  });

  it("holds the relay through the hysteresis band instead of chattering", () => {
    dispatch("POST", "/autotune/start", { setpoint: 900, hysteresis: 5 });
    vi.advanceTimersByTime(1000);

    // Inside the band the latch keeps its last answer, so a reading that has
    // not reached either threshold cannot flip the output.
    const before = dutyOf();
    state.autotune.currentTemp = 900;
    expect(dutyOf()).toBe(before);
  });

  it("drops back to zero once the tune stops", () => {
    dispatch("POST", "/autotune/start", { setpoint: 900, hysteresis: 5 });
    vi.advanceTimersByTime(1000);
    dispatch("POST", "/autotune/stop", {});
    expect(dutyOf()).toBe(0);
  });
});
