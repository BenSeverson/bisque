import { describe, it, expect, vi } from "vitest";
import { commitApiTokenChange, API_TOKEN_MAX_LENGTH } from "./apiToken";

describe("commitApiTokenChange", () => {
  it("persists a new token before switching the client over to it", async () => {
    const order: string[] = [];
    const save = vi.fn(async () => {
      order.push("save");
    });
    const activate = vi.fn(() => {
      order.push("activate");
    });

    await commitApiTokenChange({ kind: "set", token: "s3cret" }, save, activate);

    expect(save).toHaveBeenCalledWith("s3cret");
    expect(activate).toHaveBeenCalledWith("s3cret");
    // The save must be authenticated with the *current* token, so the client
    // cannot adopt the new one until the device has accepted it.
    expect(order).toEqual(["save", "activate"]);
  });

  it("sends an explicit empty string to clear, then drops the client token", async () => {
    const save = vi.fn(async () => {});
    const activate = vi.fn();

    await commitApiTokenChange({ kind: "clear" }, save, activate);

    expect(save).toHaveBeenCalledWith("");
    expect(activate).toHaveBeenCalledWith(null);
  });

  it("leaves the client token untouched when the save fails", async () => {
    const save = vi.fn(async () => {
      throw new Error("401");
    });
    const activate = vi.fn();

    await expect(
      commitApiTokenChange({ kind: "set", token: "rotated" }, save, activate),
    ).rejects.toThrow("401");

    // This is the lockout: adopting a token the device never stored leaves
    // every later request unauthenticated.
    expect(activate).not.toHaveBeenCalled();
  });

  it("rejects a token longer than the firmware can store, before saving", async () => {
    const save = vi.fn(async () => {});
    const activate = vi.fn();
    const tooLong = "x".repeat(API_TOKEN_MAX_LENGTH + 1);

    await expect(
      commitApiTokenChange({ kind: "set", token: tooLong }, save, activate),
    ).rejects.toThrow(/too long/i);

    expect(save).not.toHaveBeenCalled();
    expect(activate).not.toHaveBeenCalled();
  });

  it("accepts a token exactly at the limit", async () => {
    const save = vi.fn(async () => {});
    const activate = vi.fn();
    const atLimit = "x".repeat(API_TOKEN_MAX_LENGTH);

    await commitApiTokenChange({ kind: "set", token: atLimit }, save, activate);

    expect(save).toHaveBeenCalledWith(atLimit);
  });
});
