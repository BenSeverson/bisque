/**
 * Client-side lifecycle of a PID auto-tune run.
 *
 * The UI cannot read "is an auto-tune running" straight off the status query,
 * for two reasons:
 *
 *  1. The query is cached. Right after a successful POST /autotune/start the
 *     cache still holds the frame fetched at mount, whose state is "idle".
 *     Treating that as the end of the run instantly cancelled the run in the
 *     UI *and* switched polling off (`refetchInterval` is gated on the same
 *     flag), so no fresh frame ever arrived to correct it (issue #122).
 *  2. Even a genuinely fresh frame can read "idle" for a moment: the firmware
 *     start handler only `xQueueSend`s the command, so the firing engine has
 *     not necessarily picked it up by the next poll.
 *
 * So the run gets an explicit pending phase: `starting` polls, but only a
 * `running` frame promotes it, and only a `running` run can end. Anything else
 * inside the grace window is treated as "not yet"; past the window the start is
 * reported as failed — never as a completion.
 */
export type AutotuneSession =
  /** `settledAt` marks a run we just ended; see the adopt rule below. */
  | { phase: "idle"; settledAt?: number }
  | { phase: "starting"; requestedAt: number }
  | { phase: "running" };

/**
 * How a run ended, for the one-shot toast.
 *
 * `stopped` is deliberately distinct from `completed`: the firmware maps every
 * firing status that is neither IDLE nor AUTOTUNE to "stopped", so an aborted
 * or errored run used to be announced as "Auto-tune complete" — telling the
 * user gains had been measured when none had.
 *
 * `unconfirmed` is a start that never showed up as a run. It deliberately
 * claims nothing more: the firmware reports a finished run and a run that never
 * began identically (both plain IDLE), so a start left unconfirmed — because it
 * failed, or because the whole run elapsed while the tab was hidden and polling
 * paused — cannot honestly be called either a success or a failure.
 */
export type AutotuneOutcome = "completed" | "stopped" | "unconfirmed";

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
 * resume polling and then announce a completion for an aborted run.
 */
export function endAutotuneSession(now: number): AutotuneSession {
  return { phase: "idle", settledAt: now };
}

/** Whether the status query should be polling — true for a pending start too. */
export function isAutotunePolling(session: AutotuneSession): boolean {
  return session.phase !== "idle";
}

/**
 * Fold one observed status frame into the session.
 *
 * `state` is the raw `AutotuneStatus.state` string ("running" | "idle" |
 * "stopped" from the firmware, plus "complete" from the mock/simulator), or
 * undefined when no frame has been fetched. `observedAt` is when that frame was
 * fetched (React Query's `dataUpdatedAt`) — *not* "now", so a cached pre-start
 * frame cannot consume the grace window.
 *
 * Returns the same session object by identity when nothing changed, so callers
 * can drive React state from it without looping.
 */
export function applyAutotuneStatus(
  session: AutotuneSession,
  state: string | undefined,
  observedAt: number,
): { session: AutotuneSession; outcome?: AutotuneOutcome } {
  if (state === "running") {
    if (session.phase === "running") return { session };
    // A run we just ended can still echo "running" for a poll or two; only a
    // frame from after that window means someone really started a new one
    // (from the LCD, another browser, or the app).
    if (session.phase === "idle" && !isSettled(session, observedAt)) return { session };
    return { session: { phase: "running" } };
  }

  switch (session.phase) {
    case "idle":
      // Nothing of ours in flight; a run started elsewhere is adopted above.
      return { session };

    case "starting":
      // `observedAt` advances only when a fetch settles, so an unreachable
      // controller walks past the window too instead of hanging on "Running".
      if (observedAt - session.requestedAt < AUTOTUNE_START_GRACE_MS) return { session };
      return { session: { phase: "idle", settledAt: observedAt }, outcome: "unconfirmed" };

    case "running":
      if (state === undefined) return { session };
      return {
        session: { phase: "idle", settledAt: observedAt },
        // The firmware reports plain IDLE once a finished run releases the
        // engine; "complete" comes from the simulator. Every other state is an
        // abort or a fault, which is not a completion.
        outcome: state === "idle" || state === "complete" ? "completed" : "stopped",
      };
  }
}

function isSettled(session: { settledAt?: number }, observedAt: number): boolean {
  return (
    session.settledAt === undefined || observedAt - session.settledAt >= AUTOTUNE_START_GRACE_MS
  );
}
