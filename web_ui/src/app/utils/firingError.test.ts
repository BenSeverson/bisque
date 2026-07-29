import { describe, it, expect } from "vitest";
import {
  describeFiringError,
  firingErrorGuidance,
  emergencyStopExplanation,
  errorCodeForTransition,
  FIRING_ERROR_CODES,
} from "./firingError";

describe("describeFiringError", () => {
  it("matches the on-device wording for every code the firmware defines", () => {
    // Mirrors error_code_description() in components/display/dashboard.c. The
    // LCD and the web should not describe the same fault differently — an
    // operator comparing the two should see one story.
    expect(describeFiringError(FIRING_ERROR_CODES.TC_FAULT)).toBe(
      "Thermocouple disconnected or shorted",
    );
    expect(describeFiringError(FIRING_ERROR_CODES.OVER_TEMP)).toBe("Over temperature");
    expect(describeFiringError(FIRING_ERROR_CODES.NOT_RISING)).toBe("Kiln not heating");
    expect(describeFiringError(FIRING_ERROR_CODES.RUNAWAY)).toBe("Heating too fast");
    expect(describeFiringError(FIRING_ERROR_CODES.EMERGENCY_STOP)).toBe("Emergency stop");
    expect(describeFiringError(FIRING_ERROR_CODES.INVALID_PROFILE)).toBe(
      "Profile invalid at this temperature",
    );
  });

  it("falls back the way the LCD does for none and for unknown codes", () => {
    expect(describeFiringError(FIRING_ERROR_CODES.NONE)).toBe("Firing halted");
    // A newer firmware can send a code this build has never heard of; showing
    // the generic line beats showing nothing or a raw integer.
    expect(describeFiringError(99)).toBe("Firing halted");
    expect(describeFiringError(undefined)).toBe("Firing halted");
  });
});

describe("firingErrorGuidance", () => {
  it("says what to actually do for faults with a physical remedy", () => {
    expect(firingErrorGuidance(FIRING_ERROR_CODES.TC_FAULT)).toMatch(/thermocouple/i);
    expect(firingErrorGuidance(FIRING_ERROR_CODES.NOT_RISING)).toMatch(/element|power/i);
  });

  it("gives guidance for an emergency stop, which otherwise reads as a dead end", () => {
    // "Emergency Stop: ACTIVE" with no next step was the complaint in #164.
    const g = firingErrorGuidance(FIRING_ERROR_CODES.EMERGENCY_STOP);
    expect(g).toBeTruthy();
    expect(g).toMatch(/clear|start|restart/i);
  });

  it("returns null rather than filler when there is nothing useful to add", () => {
    expect(firingErrorGuidance(FIRING_ERROR_CODES.NONE)).toBeNull();
    expect(firingErrorGuidance(99)).toBeNull();
  });
});

describe("emergencyStopExplanation", () => {
  it("names the trip's real cause, because every trip raises the same flag", () => {
    // safety_emergency_stop_cause() is called with TC_FAULT and OVER_TEMP too,
    // so the flag alone cannot tell you which one happened.
    expect(emergencyStopExplanation(FIRING_ERROR_CODES.OVER_TEMP).cause).toBe("Over temperature");
    expect(emergencyStopExplanation(FIRING_ERROR_CODES.TC_FAULT).cause).toBe(
      "Thermocouple disconnected or shorted",
    );
  });

  it("never tells an operator to start another firing after an over-temp or runaway trip", () => {
    // The bug this replaces: the code-5 line was rendered unconditionally, so
    // an over-temperature trip advised starting a new firing to clear it.
    for (const code of [FIRING_ERROR_CODES.OVER_TEMP, FIRING_ERROR_CODES.RUNAWAY]) {
      const { guidance } = emergencyStopExplanation(code);
      expect(guidance).toBeNull();
    }
  });

  it("keeps the clear-it advice for a bare stop, where it is accurate", () => {
    // No firing running means no code was recorded, and only then is "start a
    // firing to clear it" the right thing to say.
    for (const code of [0, undefined, null]) {
      const { cause, guidance } = emergencyStopExplanation(code);
      expect(cause).toBe("Emergency stop");
      expect(guidance).toMatch(/clears a stale stop/);
    }
  });
});

describe("errorCodeForTransition", () => {
  const enteredAt = 1000;

  it("withholds a code fetched before the failure it would be explaining", () => {
    // React Query serves the previous value while refetching, so a second
    // failure would otherwise open by naming the first failure's cause.
    expect(
      errorCodeForTransition({
        code: FIRING_ERROR_CODES.TC_FAULT,
        dataUpdatedAt: 999,
        errorEnteredAt: enteredAt,
      }),
    ).toBeUndefined();
  });

  it("accepts a code fetched at or after the transition", () => {
    for (const dataUpdatedAt of [enteredAt, enteredAt + 1]) {
      expect(
        errorCodeForTransition({
          code: FIRING_ERROR_CODES.NOT_RISING,
          dataUpdatedAt,
          errorEnteredAt: enteredAt,
        }),
      ).toBe(FIRING_ERROR_CODES.NOT_RISING);
    }
  });

  it("withholds everything when there is no failure in progress", () => {
    expect(
      errorCodeForTransition({
        code: FIRING_ERROR_CODES.TC_FAULT,
        dataUpdatedAt: 9999,
        errorEnteredAt: null,
      }),
    ).toBeUndefined();
  });
});
