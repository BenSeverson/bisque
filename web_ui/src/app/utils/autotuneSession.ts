import type { AutotuneState } from "../services/api";

/**
 * Client-side lifecycle of a PID auto-tune run.
 *
 * The firmware now reports terminal outcomes distinctly — `complete` when gains
 * were measured and persisted, `failed` when the run ended without them — so the
 * UI no longer has to infer an ending from a plain `idle` frame and hedge about
 * it (#216). What is left here is one genuinely client-side problem the firmware
 * cannot solve for us:
 *
 *   Right after a successful POST /autotune/start, the status query's cache
 *   still holds the frame fetched at mount, whose state is `idle`. Treating that
 *   as the truth would end the run in the UI *and* switch polling off
 *   (`refetchInterval` is gated on the same flag), so no fresh frame would ever
 *   arrive to correct it (#122). The start handler also only `xQueueSend`s the
 *   command, so even a genuinely fresh frame can read `idle` for a poll or two.
 *
 * Hence the `starting` phase: it polls, and an `idle` frame during it means "not
 * yet", not "over". What changed with #216 is the *verdict*. `idle` is now a
 * positive statement — nothing is running and nothing has finished — so a start
 * that never takes hold is reported as `not-started`, a fact, rather than the
 * old `unconfirmed` hedge that could not distinguish a failed start from a whole
 * run that elapsed unobserved.
 */
export type AutotuneSession =
  /** `settledAt` marks a run we just ended; see the adopt rule below. */
  | { phase: "idle"; settledAt?: number }
  | { phase: "starting"; requestedAt: number }
  | { phase: "running" };

/**
 * How a run ended, for the one-shot toast.
 *
 * All four are now read straight off the firmware rather than inferred:
 *
 * - `completed` — the controller reported `complete`; gains were measured and saved.
 * - `failed` — the controller reported `failed`; the run ended without usable gains.
 * - `stopped` — the run was aborted, by this client, another one, or the LCD.
 * - `not-started` — the controller never picked the start up; nothing ran.
 */
export type AutotuneOutcome = "completed" | "failed" | "stopped" | "not-started";

export const IDLE_AUTOTUNE_SESSION: AutotuneSession = { phase: "idle" };

/**
 * How long a queued start/stop may go unreflected in the status before the UI
 * stops believing frames that could predate it.
 *
 * Generous next to both the command-queue hand-off and the 2 s poll interval,
 * so a slow controller is never mistaken for a failed start.
 */
export const AUTOTUNE_START_GRACE_MS = 10_000;

export function beginAutotuneSession(now: number): AutotuneSession {
  return { phase: "starting", requestedAt: now };
}

/**
 * End the run locally (an explicit Stop, which toasts on its own).
 *
 * Records when, because the stop is queued asynchronously as well: a status
 * frame fetched around it can still say "running", and re-adopting that would
 * resume polling and then announce an outcome for an aborted run.
 */
export function endAutotuneSession(now: number): AutotuneSession {
  return { phase: "idle", settledAt: now };
}

/** Whether the status query should be polling — true for a pending start too. */
export function isAutotunePolling(session: AutotuneSession): boolean {
  return session.phase !== "idle";
}

/** Terminal states carry their own verdict; no inference needed. */
function terminalOutcome(state: AutotuneState): AutotuneOutcome | undefined {
  switch (state) {
    case "complete":
      return "completed";
    case "failed":
      return "failed";
    case "stopped":
      return "stopped";
    // `idle` is terminal in the sense that nothing is running, but on its own it
    // does not say a run *ended* — it is also the state before one begins. The
    // caller's phase decides what it means.
    case "idle":
    case "running":
      return undefined;
  }
}

/**
 * Fold one observed status frame into the session.
 *
 * `state` is the raw `AutotuneStatus.state`, or undefined when no frame has been
 * fetched. `observedAt` is when that frame was fetched (React Query's
 * `dataUpdatedAt`) — *not* "now", so a cached pre-start frame cannot consume the
 * grace window.
 *
 * Returns the same session object by identity when nothing changed, so callers
 * can drive React state from it without looping.
 */
export function applyAutotuneStatus(
  session: AutotuneSession,
  state: AutotuneState | undefined,
  observedAt: number,
  /* Whether `observedAt` reflects a status that actually arrived. React Query
     advances errorUpdatedAt on failed fetches too, so a merged timestamp walks
     forward while the controller is unreachable. Defaults to true: callers with
     no error signal are reporting a real observation. */
  observation: { succeeded: boolean } = { succeeded: true },
): { session: AutotuneSession; outcome?: AutotuneOutcome } {
  if (state === "running") {
    if (session.phase === "running") return { session };
    // A run we just ended can still echo "running" for a poll or two; only a
    // frame from after that window means someone really started a new one
    // (from the LCD, another browser, or the app).
    if (session.phase === "idle" && !isSettled(session, observedAt)) return { session };
    return { session: { phase: "running" } };
  }

  // A terminal frame is believed in any phase where we have something in flight.
  // This is what #216 bought: a run that began and finished between two polls —
  // or entirely while the tab was hidden — still reports its real outcome
  // instead of decaying into a hedge.
  const terminal = state === undefined ? undefined : terminalOutcome(state);
  if (terminal && session.phase !== "idle") {
    if (session.phase === "starting" && !observation.succeeded) return { session };
    return { session: { phase: "idle", settledAt: observedAt }, outcome: terminal };
  }

  switch (session.phase) {
    case "idle":
      // Nothing of ours in flight; a run started elsewhere is adopted above.
      return { session };

    case "starting":
      // Only a status that actually arrived may end a start the controller
      // accepted. Letting failed fetches age the window out would stop polling
      // and hide the Stop button while the kiln might still be heating, and
      // would claim the start was dropped when the controller said nothing at
      // all. An unreachable device stays pending and stop-capable;
      // ConnectionBanner is what tells the user it is unreachable.
      if (!observation.succeeded) return { session };
      if (observedAt - session.requestedAt < AUTOTUNE_START_GRACE_MS) return { session };
      // Past the window and still plainly `idle`. Since a finished run would say
      // `complete` or `failed`, this is now a definite statement: the controller
      // never started one.
      return { session: { phase: "idle", settledAt: observedAt }, outcome: "not-started" };

    case "running":
      // `idle` while we believed a run was in flight means it was cancelled
      // somewhere else — the engine clears the autotune state on cancel, so a
      // completion would have said `complete`.
      if (state === undefined) return { session };
      return { session: { phase: "idle", settledAt: observedAt }, outcome: "stopped" };
  }
}

function isSettled(session: { settledAt?: number }, observedAt: number): boolean {
  return (
    session.settledAt === undefined || observedAt - session.settledAt >= AUTOTUNE_START_GRACE_MS
  );
}
