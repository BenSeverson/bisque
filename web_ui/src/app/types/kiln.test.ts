import { describe, it, expect } from "vitest";
import { coerceFiringStatus } from "./kiln";

describe("coerceFiringStatus", () => {
  it("preserves valid statuses", () => {
    for (const s of [
      "idle",
      "heating",
      "holding",
      "cooling",
      "complete",
      "error",
      "paused",
      "autotune",
    ] as const) {
      expect(coerceFiringStatus(s)).toBe(s);
    }
  });

  it("falls back to 'idle' for unknown values", () => {
    expect(coerceFiringStatus("unknown")).toBe("idle");
    expect(coerceFiringStatus("RUNNING")).toBe("idle");
    expect(coerceFiringStatus("")).toBe("idle");
  });

  it("falls back to 'idle' for null/undefined", () => {
    expect(coerceFiringStatus(null)).toBe("idle");
    expect(coerceFiringStatus(undefined)).toBe("idle");
  });
});
