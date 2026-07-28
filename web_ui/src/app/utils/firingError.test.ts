import { describe, it, expect } from "vitest";
import { describeFiringError, firingErrorGuidance, FIRING_ERROR_CODES } from "./firingError";

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
