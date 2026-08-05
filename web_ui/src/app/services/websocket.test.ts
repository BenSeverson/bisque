import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { WSMessage, WSConnectionState } from "./websocket";

/**
 * The reconnect state machine is the live-firing telemetry pipe: everything the
 * dashboard shows during a firing arrives through it, and every failure mode
 * here is invisible until a kiln is actually running. The three that matter are
 * a reconnect that never fires (readings freeze at the last frame), a reconnect
 * storm (a timer per close event), and `setAuthToken()` leaving
 * `intentionalClose` latched so the *next* genuine drop is silently ignored.
 *
 * Driven against a fake WebSocket rather than a real one — jsdom's would try to
 * open a socket, and none of the transitions under test (a drop three seconds
 * before a retry, a constructor that throws) are reachable from a live server.
 */

/** Sockets constructed since the last reset, oldest first. */
let sockets: FakeWebSocket[] = [];
/** When set, the next `new WebSocket()` throws instead of constructing. */
let constructorError: Error | null = null;

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState: number = FakeWebSocket.CONNECTING;
  closeCount = 0;

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((err: unknown) => void) | null = null;

  constructor(readonly url: string) {
    if (constructorError) throw constructorError;
    sockets.push(this);
  }

  close() {
    this.closeCount++;
    this.readyState = FakeWebSocket.CLOSED;
    // A real socket fires onclose asynchronously after close(); the production
    // code detaches handlers before every close it initiates, so whether we
    // fire here or not it must never see one. Firing it makes that explicit.
    this.onclose?.();
  }

  /** Simulate the server accepting the connection. */
  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  /** Simulate the far end going away (device reboot, Wi-Fi drop). */
  drop() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }

  send(data: string) {
    this.onmessage?.({ data });
  }
}

const RECONNECT_DELAY_MS = 3000;

/** Fresh module instance per test — `kilnWS` is a long-lived singleton. */
async function freshWS() {
  vi.resetModules();
  return (await import("./websocket")).kilnWS;
}

function lastSocket(): FakeWebSocket {
  const ws = sockets[sockets.length - 1];
  if (!ws) throw new Error("no socket was constructed");
  return ws;
}

beforeEach(() => {
  sockets = [];
  constructorError = null;
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", FakeWebSocket);
  // websocket.ts logs every transition under import.meta.env.DEV, which vitest
  // sets. The transitions themselves are asserted; the noise is not.
  vi.spyOn(console, "log").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("kilnWS: URL construction", () => {
  it("targets the device's /api/v1/ws over ws:// on a plain-http page", async () => {
    const ws = await freshWS();
    ws.connect();
    expect(lastSocket().url).toBe(`ws://${window.location.host}/api/v1/ws`);
  });

  // The wss:// upgrade needs an https document, and jsdom's window.location is
  // unforgeable — it lives in websocket.secure.test.ts, which sets the page URL
  // through the environment instead.

  it("carries the API token as a query parameter, percent-encoded", async () => {
    // The WebSocket API has no way to set an Authorization header, so the token
    // rides in the URL. A token with URL metacharacters must not truncate it.
    const ws = await freshWS();
    ws.setAuthToken("a b&c=d");
    ws.connect();
    expect(lastSocket().url).toBe(
      `ws://${window.location.host}/api/v1/ws?token=${encodeURIComponent("a b&c=d")}`,
    );
  });
});

describe("kilnWS: connect() idempotence", () => {
  it("does not open a second socket while one is connecting", async () => {
    const ws = await freshWS();
    ws.connect();
    ws.connect();
    expect(sockets).toHaveLength(1);
  });

  it("does not open a second socket while one is open", async () => {
    const ws = await freshWS();
    ws.connect();
    lastSocket().open();
    ws.connect();
    expect(sockets).toHaveLength(1);
  });

  it("opens a replacement once the previous socket has closed", async () => {
    const ws = await freshWS();
    ws.connect();
    lastSocket().open();
    lastSocket().drop();
    ws.connect();
    expect(sockets).toHaveLength(2);
  });
});

describe("kilnWS: reconnect state machine", () => {
  it("reconnects after an unexpected drop", async () => {
    const ws = await freshWS();
    ws.connect();
    lastSocket().open();
    lastSocket().drop();

    expect(sockets).toHaveLength(1);
    vi.advanceTimersByTime(RECONNECT_DELAY_MS);
    expect(sockets).toHaveLength(2);
  });

  it("waits the full delay before retrying", async () => {
    const ws = await freshWS();
    ws.connect();
    lastSocket().open();
    lastSocket().drop();

    vi.advanceTimersByTime(RECONNECT_DELAY_MS - 1);
    expect(sockets).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(2);
  });

  it("keeps retrying while the device stays down", async () => {
    const ws = await freshWS();
    ws.connect();
    lastSocket().open();

    for (let i = 0; i < 3; i++) {
      lastSocket().drop();
      vi.advanceTimersByTime(RECONNECT_DELAY_MS);
    }
    // One initial + three retries. A machine that gives up after the first
    // failed retry leaves the tab dead until a manual reload.
    expect(sockets).toHaveLength(4);
  });

  it("arms only one retry timer no matter how many closes arrive", async () => {
    const ws = await freshWS();
    ws.connect();
    lastSocket().open();
    expect(vi.getTimerCount()).toBe(0);

    // A socket that closes, and an error path that also closes, both land in
    // scheduleReconnect(). Without the pending-timer guard each close arms its
    // own timer. Counting timers rather than sockets is the point: connect()'s
    // own idempotence hides the surplus once they all fire in the same tick,
    // and would go on hiding it right up until two of them straddle a tick.
    const socket = lastSocket();
    socket.drop();
    socket.drop();
    socket.drop();

    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(RECONNECT_DELAY_MS);
    expect(sockets).toHaveLength(2);
  });

  it("leaves no timer armed once a retry has fired", async () => {
    // The callback nulls reconnectTimer before reconnecting; if it did not, the
    // guard above would latch permanently and the *next* drop would never retry.
    const ws = await freshWS();
    ws.connect();
    lastSocket().open();
    lastSocket().drop();
    vi.advanceTimersByTime(RECONNECT_DELAY_MS);

    expect(vi.getTimerCount()).toBe(0);
    lastSocket().drop();
    expect(vi.getTimerCount()).toBe(1);
  });

  it("cancels the pending retry once a connection comes back up", async () => {
    const ws = await freshWS();
    ws.connect();
    lastSocket().open();
    lastSocket().drop();

    // The retry fires and this time the device answers...
    vi.advanceTimersByTime(RECONNECT_DELAY_MS);
    lastSocket().open();

    // ...so no stale timer may still be armed, or it would open a duplicate
    // socket alongside the healthy one.
    vi.advanceTimersByTime(RECONNECT_DELAY_MS * 5);
    expect(sockets).toHaveLength(2);
  });

  it("goes offline and retries when the socket cannot even be constructed", async () => {
    // Blocked by a CSP or an extension: the constructor throws, so there is no
    // socket to deliver onclose and nothing else would ever arm a retry.
    constructorError = new Error("blocked");
    const ws = await freshWS();
    ws.connect();
    expect(ws.getConnectionState()).toBe("offline");

    constructorError = null;
    vi.advanceTimersByTime(RECONNECT_DELAY_MS);
    expect(sockets).toHaveLength(1);
  });

  it("does not reconnect after an intentional disconnect", async () => {
    const ws = await freshWS();
    ws.connect();
    lastSocket().open();
    ws.disconnect();

    vi.advanceTimersByTime(RECONNECT_DELAY_MS * 5);
    expect(sockets).toHaveLength(1);
  });

  it("cancels an already-armed retry when disconnect() lands first", async () => {
    // Unmounting during the three-second gap after a drop. The timer outlives
    // the component that wanted the socket unless disconnect() clears it.
    const ws = await freshWS();
    ws.connect();
    lastSocket().open();
    lastSocket().drop();
    ws.disconnect();

    vi.advanceTimersByTime(RECONNECT_DELAY_MS * 5);
    expect(sockets).toHaveLength(1);
  });

  it("reconnects normally after a disconnect/connect cycle", async () => {
    // disconnect() latches intentionalClose. connect() has to clear it, or the
    // next genuine drop is mistaken for a deliberate teardown and never retried.
    const ws = await freshWS();
    ws.connect();
    lastSocket().open();
    ws.disconnect();

    ws.connect();
    lastSocket().open();
    lastSocket().drop();
    vi.advanceTimersByTime(RECONNECT_DELAY_MS);
    expect(sockets).toHaveLength(3);
  });
});

describe("kilnWS: setAuthToken()", () => {
  it("does nothing when the token is unchanged", async () => {
    // useSettings re-renders on every poll; churning the socket each time would
    // drop telemetry once every few seconds.
    const ws = await freshWS();
    ws.setAuthToken("t1");
    ws.connect();
    ws.setAuthToken("t1");
    expect(sockets).toHaveLength(1);
    expect(lastSocket().closeCount).toBe(0);
  });

  it("does not open a socket when nothing is connected", async () => {
    // api.ts calls this at module load with a token restored from
    // sessionStorage, long before any component asks for a connection.
    const ws = await freshWS();
    ws.setAuthToken("t1");
    expect(sockets).toHaveLength(0);
  });

  it("reopens with the new credential when one is live", async () => {
    const ws = await freshWS();
    ws.setAuthToken("old");
    ws.connect();
    lastSocket().open();

    ws.setAuthToken("new");
    expect(sockets).toHaveLength(2);
    expect(sockets[0].closeCount).toBe(1);
    expect(lastSocket().url).toContain("token=new");
  });

  it("does not let the swap itself trigger a reconnect timer", async () => {
    // The old socket's close is deliberate. If it reached scheduleReconnect(),
    // the replacement opened here and a third socket three seconds later would
    // both be live, and the newer one would win the handler race arbitrarily.
    const ws = await freshWS();
    ws.setAuthToken("old");
    ws.connect();
    lastSocket().open();

    ws.setAuthToken("new");
    vi.advanceTimersByTime(RECONNECT_DELAY_MS * 5);
    expect(sockets).toHaveLength(2);
  });

  it("leaves the reconnect machine armed for the new socket", async () => {
    // The swap latches intentionalClose to suppress its own close event. The
    // replacement must not inherit it, or the freshly-authenticated socket
    // never retries — the exact window in which the user has just proved they
    // can reach the device.
    const ws = await freshWS();
    ws.setAuthToken("old");
    ws.connect();
    lastSocket().open();

    ws.setAuthToken("new");
    lastSocket().open();
    lastSocket().drop();
    vi.advanceTimersByTime(RECONNECT_DELAY_MS);
    expect(sockets).toHaveLength(3);
    expect(lastSocket().url).toContain("token=new");
  });

  it("drops the credential when the token is cleared", async () => {
    const ws = await freshWS();
    ws.setAuthToken("old");
    ws.connect();
    lastSocket().open();

    ws.setAuthToken(null);
    expect(lastSocket().url).toBe(`ws://${window.location.host}/api/v1/ws`);
  });
});

describe("kilnWS: connection state", () => {
  it("starts offline", async () => {
    const ws = await freshWS();
    expect(ws.getConnectionState()).toBe("offline");
  });

  it("walks connecting -> open -> offline", async () => {
    const ws = await freshWS();
    const seen: WSConnectionState[] = [];
    ws.subscribeStatus((s) => seen.push(s));

    ws.connect();
    lastSocket().open();
    lastSocket().drop();

    // The immediate replay on subscribe is the first entry.
    expect(seen).toEqual(["offline", "connecting", "open", "offline"]);
  });

  it("replays the current state to a late subscriber", async () => {
    // The banner mounts after the socket is already up; without the replay it
    // would show "offline" until the connection next changed.
    const ws = await freshWS();
    ws.connect();
    lastSocket().open();

    const seen: WSConnectionState[] = [];
    ws.subscribeStatus((s) => seen.push(s));
    expect(seen).toEqual(["open"]);
  });

  it("does not re-notify for a state it is already in", async () => {
    const ws = await freshWS();
    ws.connect();
    const seen: WSConnectionState[] = [];
    ws.subscribeStatus((s) => seen.push(s));
    seen.length = 0;

    // Each failed retry re-enters "connecting" from "connecting".
    lastSocket().drop();
    vi.advanceTimersByTime(RECONNECT_DELAY_MS);
    expect(seen).toEqual(["offline", "connecting"]);
  });

  it("reports offline on an intentional disconnect", async () => {
    // disconnect() detaches onclose before closing, so nothing reports the
    // close; the state would otherwise stay stuck at "open" and the dashboard
    // would keep presenting the last reading as live.
    const ws = await freshWS();
    ws.connect();
    lastSocket().open();
    ws.disconnect();
    expect(ws.getConnectionState()).toBe("offline");
  });

  it("stops notifying an unsubscribed status handler", async () => {
    const ws = await freshWS();
    const seen: WSConnectionState[] = [];
    const off = ws.subscribeStatus((s) => seen.push(s));
    off();
    ws.connect();
    expect(seen).toEqual(["offline"]);
  });
});

describe("kilnWS: message delivery", () => {
  const frame: WSMessage = {
    type: "ota_progress",
    data: { phase: "flash", percent: 42 },
  };

  it("delivers parsed frames to every subscriber", async () => {
    const ws = await freshWS();
    const a = vi.fn();
    const b = vi.fn();
    ws.subscribe(a);
    ws.subscribe(b);
    ws.connect();
    lastSocket().open();
    lastSocket().send(JSON.stringify(frame));

    expect(a).toHaveBeenCalledWith(frame);
    expect(b).toHaveBeenCalledWith(frame);
  });

  it("stops delivering to an unsubscribed handler", async () => {
    const ws = await freshWS();
    const handler = vi.fn();
    const off = ws.subscribe(handler);
    ws.connect();
    lastSocket().open();
    off();
    lastSocket().send(JSON.stringify(frame));

    expect(handler).not.toHaveBeenCalled();
  });

  it("survives a malformed frame without tearing down the socket", async () => {
    // A truncated frame must not take the connection with it — the next good
    // frame is a second away.
    const ws = await freshWS();
    const handler = vi.fn();
    ws.subscribe(handler);
    ws.connect();
    lastSocket().open();

    lastSocket().send("{not json");
    expect(handler).not.toHaveBeenCalled();
    expect(ws.getConnectionState()).toBe("open");

    lastSocket().send(JSON.stringify(frame));
    expect(handler).toHaveBeenCalledWith(frame);
  });

  it("keeps delivering frames across a reconnect", async () => {
    const ws = await freshWS();
    const handler = vi.fn();
    ws.subscribe(handler);
    ws.connect();
    lastSocket().open();
    lastSocket().drop();
    vi.advanceTimersByTime(RECONNECT_DELAY_MS);
    lastSocket().open();
    lastSocket().send(JSON.stringify(frame));

    // Subscriptions live on the client, not the socket, so a reconnect must not
    // silently orphan them.
    expect(handler).toHaveBeenCalledWith(frame);
  });

  it("ignores frames from a socket that has been replaced", async () => {
    // The pre-rotation socket may still have bytes in flight. Its handlers are
    // detached, so anything it delivers is dropped rather than mixed in.
    const ws = await freshWS();
    const handler = vi.fn();
    ws.subscribe(handler);
    ws.setAuthToken("old");
    ws.connect();
    lastSocket().open();
    const stale = lastSocket();

    ws.setAuthToken("new");
    stale.send(JSON.stringify(frame));
    expect(handler).not.toHaveBeenCalled();
  });
});
