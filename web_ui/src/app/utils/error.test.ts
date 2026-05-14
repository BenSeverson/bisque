import { describe, it, expect } from "vitest";
import { toErrorMessage } from "./error";

describe("toErrorMessage", () => {
  it("extracts .message from Error instances", () => {
    expect(toErrorMessage(new Error("boom"))).toBe("boom");
  });

  it("recognizes Error subclasses", () => {
    class CustomError extends Error {}
    expect(toErrorMessage(new CustomError("custom"))).toBe("custom");
  });

  it("falls back for non-Error throwables", () => {
    expect(toErrorMessage("plain string")).toBe("Unknown error");
    expect(toErrorMessage({ message: "lookalike" })).toBe("Unknown error");
    expect(toErrorMessage(null)).toBe("Unknown error");
    expect(toErrorMessage(undefined)).toBe("Unknown error");
  });
});
