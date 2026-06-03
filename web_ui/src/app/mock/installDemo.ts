/**
 * In-page mock backend for the static GitHub Pages demo (the `__DEMO__` build).
 *
 * GitHub Pages serves static files only — there is no HTTP/WebSocket server to
 * talk to. This module patches `window.fetch` and `window.WebSocket` so the
 * UNCHANGED app code (`services/api.ts`, `services/websocket.ts`) drives the
 * existing in-browser kiln simulator (`mock-server/`) instead of a real device.
 *
 * It is imported ONLY via a gated dynamic `import()` in `main.tsx`
 * (`if (__DEMO__) ...`), so the simulator never ships in the firmware bundle.
 * This is the single `src/` file allowed to import from `mock-server/`.
 */
import { dispatch } from "../../../mock-server/router";
import { state } from "../../../mock-server/state";
import type { DispatchResult } from "../../../mock-server/router";

const API_PREFIX = "/api/v1";
const WS_PATH = "/api/v1/ws";

/** Simulation speed multiplier — 60× real time so a firing is watchable in minutes. */
const DEMO_SPEED = 60;

let installed = false;

export function installDemo(): void {
  if (installed) return;
  installed = true;

  state.speed = DEMO_SPEED;
  installFetch();
  installWebSocket();
}

// --- fetch interception ------------------------------------------------------

function installFetch(): void {
  const originalFetch = window.fetch.bind(window);

  window.fetch = async function (input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    const path = new URL(extractUrl(input), window.location.href).pathname;

    // Anything that isn't an API call (the page's own assets) goes to the real
    // fetch. The WebSocket endpoint is handled by the WebSocket patch, not here.
    if (!path.startsWith(API_PREFIX) || path === WS_PATH) {
      return originalFetch(input, init);
    }

    const method = (
      init?.method ?? (input instanceof Request ? input.method : "GET")
    ).toUpperCase();
    const apiPath = path.replace(API_PREFIX, "");
    const body = await extractBody(input, init);

    return toResponse(dispatch(method, apiPath, body));
  };
}

function extractUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return input.url; // Request
}

async function extractBody(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Record<string, unknown>> {
  if (init?.body != null) {
    return typeof init.body === "string" ? safeJsonParse(init.body) : {};
  }
  if (input instanceof Request) {
    const text = await input.clone().text();
    return text ? safeJsonParse(text) : {};
  }
  return {};
}

function safeJsonParse(text: string): Record<string, unknown> {
  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

function toResponse(result: DispatchResult): Response {
  const headers = new Headers(result.headers ?? {});
  if (result.text !== undefined) {
    headers.set("Content-Type", result.contentType ?? "text/plain");
    return new Response(result.text, { status: result.status, headers });
  }
  headers.set("Content-Type", result.contentType ?? "application/json");
  return new Response(JSON.stringify(result.json ?? null), {
    status: result.status,
    headers,
  });
}

// --- WebSocket interception --------------------------------------------------

/**
 * A minimal WebSocket stand-in for `/api/v1/ws`. It subscribes to the
 * simulator's broadcast fan-out and replays each `temp_update` to `onmessage`.
 *
 * Critical behaviours (see services/websocket.ts):
 *  - `onopen` fires ASYNCHRONOUSLY (the caller attaches handlers after the
 *    constructor returns; a synchronous open would be missed).
 *  - it NEVER auto-closes — an `onclose` would trigger the client's 3 s
 *    reconnect loop forever. Only an explicit `close()` fires `onclose`.
 */
class DemoWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readonly url: string;
  readyState: number = DemoWebSocket.CONNECTING;
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;

  private unsubscribe: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    setTimeout(() => {
      if (this.readyState !== DemoWebSocket.CONNECTING) return;
      this.readyState = DemoWebSocket.OPEN;

      const deliver = (msg: string) => {
        if (this.readyState === DemoWebSocket.OPEN) this.onmessage?.({ data: msg });
      };
      state.subscribers.add(deliver);
      this.unsubscribe = () => state.subscribers.delete(deliver);

      this.onopen?.({});
    }, 0);
  }

  send(): void {
    // Receive-only mock: the kiln pushes temp updates; the client never sends.
  }

  close(): void {
    if (this.readyState === DemoWebSocket.CLOSED) return;
    this.readyState = DemoWebSocket.CLOSED;
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.onclose?.({});
  }
}

function installWebSocket(): void {
  const OriginalWebSocket = window.WebSocket;

  function WebSocketProxy(url: string | URL, protocols?: string | string[]): WebSocket {
    const href = typeof url === "string" ? url : url.href;
    if (new URL(href, window.location.href).pathname === WS_PATH) {
      return new DemoWebSocket(href) as unknown as WebSocket;
    }
    return new OriginalWebSocket(url, protocols);
  }

  // Carry the static readyState constants the client reads off `WebSocket.*`.
  WebSocketProxy.CONNECTING = DemoWebSocket.CONNECTING;
  WebSocketProxy.OPEN = DemoWebSocket.OPEN;
  WebSocketProxy.CLOSING = DemoWebSocket.CLOSING;
  WebSocketProxy.CLOSED = DemoWebSocket.CLOSED;

  window.WebSocket = WebSocketProxy as unknown as typeof WebSocket;
}
