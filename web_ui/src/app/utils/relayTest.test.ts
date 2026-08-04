import { describe, it, expect } from "vitest";
import {
  prepareRelayDuration,
  RELAY_TEST_MIN_SECONDS,
  RELAY_TEST_MAX_SECONDS,
  RELAY_TEST_DEFAULT_SECONDS,
} from "./relayTest";

describe("prepareRelayDuration", () => {
  it("accepts the range the firmware honours, endpoints included", () => {
    for (const s of [RELAY_TEST_MIN_SECONDS, RELAY_TEST_DEFAULT_SECONDS, RELAY_TEST_MAX_SECONDS]) {
      expect(prepareRelayDuration(s)).toEqual({ ok: true, seconds: s });
    }
  });

  it("refuses a duration the firmware would silently clamp", () => {
    // handle_diag_relay() answers 200 with durationSeconds: 10 for a request of
    // 30, so accepting it here would show a success toast for a pulse a third
    // the length the user asked for.
    expect(prepareRelayDuration(30)).toMatchObject({ ok: false });
    expect(prepareRelayDuration(0)).toMatchObject({ ok: false });
    expect(prepareRelayDuration(-1)).toMatchObject({ ok: false });
  });

  it("refuses a fractional duration, which the firmware truncates", () => {
    // `(int)j->valuedouble` turns 1.9 into a 1-second pulse.
    expect(prepareRelayDuration(1.9)).toMatchObject({ ok: false });
  });

  it("refuses an empty field rather than sending NaN", () => {
    // parseFloat("") is NaN, and JSON.stringify writes it as null — which the
    // firmware casts to a 0-second request and then clamps up to 1.
    expect(prepareRelayDuration(NaN)).toMatchObject({ ok: false });
  });
});
