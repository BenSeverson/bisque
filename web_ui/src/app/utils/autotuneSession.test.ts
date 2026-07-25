import { describe, it, expect } from "vitest";
import {
  AUTOTUNE_START_GRACE_MS,
  IDLE_AUTOTUNE_SESSION,
  applyAutotuneStatus,
  beginAutotuneSession,
  endAutotuneSession,
  isAutotunePolling,
  type AutotuneSession,
} from "./autotuneSession";

const T0 = 1_000_000;

describe("beginAutotuneSession", () => {
  it("enters a pending 'starting' phase that already polls", () => {
    const session = beginAutotuneSession(T0);
    expect(session.phase).toBe("starting");
    expect(isAutotunePolling(session)).toBe(true);
  });

  it("does not poll while idle", () => {
    expect(isAutotunePolling(IDLE_AUTOTUNE_SESSION)).toBe(false);
  });
});

describe("applyAutotuneStatus while starting", () => {
  it("ignores a stale cached 'idle' status observed before the start request", () => {
    // The bug: the completion effect read the query cache populated at mount
    // (state "idle", fetched before the POST) and instantly declared the
    // auto-tune complete, which also switched polling back off.
    const session = beginAutotuneSession(T0);
    const next = applyAutotuneStatus(session, "idle", T0 - 5000);
    expect(next.session).toBe(session);
    expect(next.outcome).toBeUndefined();
    expect(isAutotunePolling(next.session)).toBe(true);
  });

  it("tolerates a freshly fetched 'idle' inside the start grace window", () => {
    // The firmware queues the start command (xQueueSend), so a genuinely fresh
    // status can still read "idle" for a moment after a successful POST.
    const session = beginAutotuneSession(T0);
    const next = applyAutotuneStatus(session, "idle", T0 + AUTOTUNE_START_GRACE_MS - 1);
    expect(next.session).toBe(session);
    expect(next.outcome).toBeUndefined();
  });

  it("survives several idle polls without completing", () => {
    let session = beginAutotuneSession(T0);
    for (let i = 1; i <= 4; i++) {
      const next = applyAutotuneStatus(session, "idle", T0 + i * 2000);
      expect(next.outcome).toBeUndefined();
      session = next.session;
    }
    expect(session.phase).toBe("starting");
  });

  it("confirms the run once the controller reports 'running'", () => {
    const next = applyAutotuneStatus(beginAutotuneSession(T0), "running", T0 + 2000);
    expect(next.session.phase).toBe("running");
    expect(next.outcome).toBeUndefined();
  });

  it("gives up as unconfirmed, never as a completion, once the grace window lapses", () => {
    const next = applyAutotuneStatus(
      beginAutotuneSession(T0),
      "idle",
      T0 + AUTOTUNE_START_GRACE_MS,
    );
    expect(next.session.phase).toBe("idle");
    expect(next.outcome).toBe("unconfirmed");
  });

  it("holds the pending phase when no status frame has arrived yet", () => {
    const session = beginAutotuneSession(T0);
    const next = applyAutotuneStatus(session, undefined, 0);
    expect(next.session).toBe(session);
    expect(next.outcome).toBeUndefined();
  });

  it("times out rather than hanging on 'Running' when every poll keeps failing", () => {
    // observedAt only advances when a fetch settles, so a run of failed polls
    // eventually walks past the window and reports the start as failed.
    const next = applyAutotuneStatus(
      beginAutotuneSession(T0),
      undefined,
      T0 + AUTOTUNE_START_GRACE_MS,
    );
    expect(next.session.phase).toBe("idle");
    expect(next.outcome).toBe("unconfirmed");
  });
});

describe("applyAutotuneStatus while running", () => {
  const running = applyAutotuneStatus(beginAutotuneSession(T0), "running", T0 + 2000).session;

  it("stays running while the controller says so", () => {
    const next = applyAutotuneStatus(running, "running", T0 + 4000);
    expect(next.session).toBe(running);
    expect(next.outcome).toBeUndefined();
  });

  it("completes when the controller returns to idle or reports complete", () => {
    for (const state of ["idle", "complete"]) {
      const next = applyAutotuneStatus(running, state, T0 + 60_000);
      expect(next.session.phase).toBe("idle");
      expect(next.outcome).toBe("completed");
    }
  });

  it("reports a stop as a stop, not as a completion", () => {
    // The firmware maps every non-idle, non-autotune firing status to "stopped".
    // Calling that "Auto-tune complete" told the user gains had been tuned when
    // the run had actually been aborted.
    const next = applyAutotuneStatus(running, "stopped", T0 + 60_000);
    expect(next.session.phase).toBe("idle");
    expect(next.outcome).toBe("stopped");
  });

  it("treats an unrecognised state as a stop rather than a success", () => {
    const next = applyAutotuneStatus(running, "wat", T0 + 60_000);
    expect(next.outcome).toBe("stopped");
  });

  it("keeps running when a poll fails and there is no data", () => {
    const next = applyAutotuneStatus(running, undefined, T0 + 60_000);
    expect(next.session).toBe(running);
    expect(next.outcome).toBeUndefined();
  });
});

describe("applyAutotuneStatus while idle", () => {
  it("adopts a run started elsewhere (LCD, another browser)", () => {
    const next = applyAutotuneStatus(IDLE_AUTOTUNE_SESSION, "running", T0);
    expect(next.session.phase).toBe("running");
    expect(next.outcome).toBeUndefined();
  });

  it("stays idle — and silent — for every non-running state", () => {
    for (const state of ["idle", "stopped", "complete", undefined]) {
      const next = applyAutotuneStatus(IDLE_AUTOTUNE_SESSION, state, T0);
      expect(next.session).toBe(IDLE_AUTOTUNE_SESSION);
      expect(next.outcome).toBeUndefined();
    }
  });

  it("does not re-adopt a 'running' frame that may predate our stop", () => {
    // Stop is queued asynchronously too, so the controller can still report
    // "running" just after the POST. Re-adopting it would restart polling and
    // then toast "Auto-tune complete" for a run the user had just aborted.
    const stopped = endAutotuneSession(T0);
    const next = applyAutotuneStatus(stopped, "running", T0 + 500);
    expect(next.session).toBe(stopped);
    expect(next.outcome).toBeUndefined();
  });

  it("adopts a genuinely new run once the post-stop window has passed", () => {
    const next = applyAutotuneStatus(
      endAutotuneSession(T0),
      "running",
      T0 + AUTOTUNE_START_GRACE_MS,
    );
    expect(next.session.phase).toBe("running");
  });

  it("ignores a stale 'running' frame after a completion", () => {
    const running = applyAutotuneStatus(beginAutotuneSession(T0), "running", T0 + 2000).session;
    const finished = applyAutotuneStatus(running, "idle", T0 + 60_000);
    expect(finished.outcome).toBe("completed");
    const echo = applyAutotuneStatus(finished.session, "running", T0 + 60_500);
    expect(echo.session).toBe(finished.session);
    expect(echo.outcome).toBeUndefined();
  });
});

describe("applyAutotuneStatus: an unreachable controller (#213 review)", () => {
  const START = 1_000_000;

  function starting() {
    return beginAutotuneSession(START);
  }

  it("keeps a pending start polling while status fetches are only failing", () => {
    // errorUpdatedAt advances on every failed fetch, so a merged "observedAt"
    // walks past the grace window without a single status ever arriving. The
    // POST succeeded, so the kiln may be heating — abandoning the session here
    // stops polling and hides the Stop button.
    const s = starting();
    const r = applyAutotuneStatus(s, undefined, START + AUTOTUNE_START_GRACE_MS + 5_000, {
      succeeded: false,
    });
    expect(r.session.phase).toBe("starting");
    expect(isAutotunePolling(r.session)).toBe(true);
    expect(r.outcome).toBeUndefined();
  });

  it("never claims the controller reports idle when nothing was received", () => {
    const s = starting();
    const r = applyAutotuneStatus(s, undefined, START + 60_000, { succeeded: false });
    expect(r.outcome).not.toBe("unconfirmed");
  });

  it("still gives up when the controller genuinely answers idle past the window", () => {
    // A real reply of "idle" past the window is still unconfirmed — that is the
    // #122 behaviour and must not regress.
    const s = starting();
    const r = applyAutotuneStatus(s, "idle", START + AUTOTUNE_START_GRACE_MS + 1, {
      succeeded: true,
    });
    expect(r.session.phase).toBe("idle");
    expect(r.outcome).toBe("unconfirmed");
  });

  it("recovers when status comes back after a failed stretch", () => {
    let s = starting();
    s = applyAutotuneStatus(s, undefined, START + 30_000, { succeeded: false }).session;
    const r = applyAutotuneStatus(s, "running", START + 31_000, { succeeded: true });
    expect(r.session.phase).toBe("running");
  });

  it("keeps a running session running through failed fetches", () => {
    const s: AutotuneSession = { phase: "running" };
    const r = applyAutotuneStatus(s, undefined, START + 99_000, { succeeded: false });
    expect(r.session.phase).toBe("running");
    expect(r.outcome).toBeUndefined();
  });
});
