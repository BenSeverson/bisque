import { describe, it, expect } from "vitest";
import { formatDuration, formatDurationFromMinutes, formatUptime } from "./time";

describe("formatDuration (seconds → Xh Ym)", () => {
  it("formats whole hours and minutes", () => {
    expect(formatDuration(3600)).toBe("1h 0m");
    expect(formatDuration(3660)).toBe("1h 1m");
    expect(formatDuration(7200 + 45 * 60)).toBe("2h 45m");
  });

  it("handles zero and sub-minute values", () => {
    expect(formatDuration(0)).toBe("0h 0m");
    expect(formatDuration(59)).toBe("0h 0m");
    expect(formatDuration(60)).toBe("0h 1m");
  });

  it("truncates fractional seconds toward zero", () => {
    expect(formatDuration(3659.9)).toBe("1h 0m");
  });
});

describe("formatDurationFromMinutes (minutes → Xh Ym)", () => {
  it("formats whole hours and minutes", () => {
    expect(formatDurationFromMinutes(60)).toBe("1h 0m");
    expect(formatDurationFromMinutes(125)).toBe("2h 5m");
  });

  it("handles zero and fractional minutes", () => {
    expect(formatDurationFromMinutes(0)).toBe("0h 0m");
    expect(formatDurationFromMinutes(59.9)).toBe("0h 59m");
  });
});

describe("formatUptime (seconds → Xh Ym Zs)", () => {
  it("includes seconds", () => {
    expect(formatUptime(3661)).toBe("1h 1m 1s");
    expect(formatUptime(45)).toBe("0h 0m 45s");
  });
});
