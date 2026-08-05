/**
 * @vitest-environment-options { "url": "https://kiln.local/" }
 *
 * Split out from websocket.test.ts purely to get an https document. jsdom's
 * `window.location` is unforgeable — it cannot be redefined from inside a test —
 * so the only way to exercise the wss:// upgrade is to load the page over https
 * in the first place. (The `environment` itself still comes from
 * vitest.config.ts's directory scoping; only the URL is set here.)
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

const constructed: string[] = [];

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((err: unknown) => void) | null = null;

  constructor(url: string) {
    constructed.push(url);
  }

  close() {}
}

beforeEach(() => {
  constructed.length = 0;
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.spyOn(console, "log").mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("kilnWS on an https page", () => {
  it("upgrades the socket to wss://", async () => {
    // Browsers block mixed content outright, so a plain ws:// from an https
    // page is not a degraded connection — it is no connection at all, and the
    // dashboard would sit permanently offline behind a TLS-terminating proxy.
    vi.resetModules();
    const { kilnWS } = await import("./websocket");
    kilnWS.connect();
    expect(constructed).toEqual(["wss://kiln.local/api/v1/ws"]);
  });
});
