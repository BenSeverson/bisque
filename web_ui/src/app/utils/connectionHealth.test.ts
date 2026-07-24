import { describe, it, expect } from "vitest";
import { deriveConnectionHealth, STALE_AFTER_MS } from "./connectionHealth";

const NOW = 1_000_000;

describe("deriveConnectionHealth", () => {
  it("is live when the socket is open and an update arrived recently", () => {
    const r = deriveConnectionHealth({ state: "open", lastUpdateAt: NOW - 1_000, now: NOW });
    expect(r.health).toBe("live");
    expect(r.msSinceUpdate).toBe(1_000);
  });

  it("is offline whenever the socket is not open, however fresh the last update", () => {
    for (const state of ["connecting", "offline"] as const) {
      const r = deriveConnectionHealth({ state, lastUpdateAt: NOW, now: NOW });
      expect(r.health).toBe("offline");
    }
  });

  it("is stale when the socket is open but updates have stopped arriving", () => {
    // The device broadcasts continuously while powered; silence on an open
    // socket means the readings on screen no longer reflect the kiln.
    const r = deriveConnectionHealth({
      state: "open",
      lastUpdateAt: NOW - (STALE_AFTER_MS + 1),
      now: NOW,
    });
    expect(r.health).toBe("stale");
  });

  it("is stale when open but no update has ever arrived", () => {
    const r = deriveConnectionHealth({ state: "open", lastUpdateAt: null, now: NOW });
    expect(r.health).toBe("stale");
    expect(r.msSinceUpdate).toBeNull();
  });

  it("treats the staleness threshold itself as still live", () => {
    const r = deriveConnectionHealth({
      state: "open",
      lastUpdateAt: NOW - STALE_AFTER_MS,
      now: NOW,
    });
    expect(r.health).toBe("live");
  });

  it("never reports a negative age if a timestamp is slightly ahead of now", () => {
    const r = deriveConnectionHealth({ state: "open", lastUpdateAt: NOW + 500, now: NOW });
    expect(r.msSinceUpdate).toBe(0);
    expect(r.health).toBe("live");
  });
});
