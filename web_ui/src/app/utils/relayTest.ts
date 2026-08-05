/** Whole seconds, mirroring handle_diag_relay's `(int)j->valuedouble` cast. */
export const RELAY_TEST_MIN_SECONDS = 1;
export const RELAY_TEST_MAX_SECONDS = 10;
export const RELAY_TEST_DEFAULT_SECONDS = 2;

export type RelayDurationResult = { ok: true; seconds: number } | { ok: false; message: string };

/**
 * Validate the relay-test pulse length before POST /api/v1/diagnostics/relay.
 *
 * The bounds mirror the clamp in handle_diag_relay() (api_handlers.c), which is
 * silent: ask for 30 s and the firmware answers 200 with `durationSeconds: 10`.
 * Rejecting out-of-range here means the number in the field is the number the
 * SSR actually closes for. The upper bound is not arbitrary — the firing engine
 * owns the pulse specifically so a test longer than the safety task's 3-second
 * heartbeat cannot trip it, and 10 s is where that arrangement was sized.
 */
export function prepareRelayDuration(seconds: number): RelayDurationResult {
  if (
    !Number.isInteger(seconds) ||
    seconds < RELAY_TEST_MIN_SECONDS ||
    seconds > RELAY_TEST_MAX_SECONDS
  ) {
    return {
      ok: false,
      message: `Duration must be a whole number of seconds between ${RELAY_TEST_MIN_SECONDS} and ${RELAY_TEST_MAX_SECONDS}`,
    };
  }
  return { ok: true, seconds };
}
