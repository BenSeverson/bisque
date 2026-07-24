export interface TempUpdateData {
  currentTemp: number;
  targetTemp: number;
  status: string;
  currentSegment: number;
  totalSegments: number;
  elapsedTime: number;
  estimatedTimeRemaining: number;
  isActive: boolean;
}

export interface OtaProgressData {
  phase: "download" | "flash";
  percent: number;
}

export interface OtaCompleteData {
  percent: number;
}

export interface OtaErrorData {
  message: string;
}

export type WSMessage =
  | { type: "temp_update"; data: TempUpdateData }
  | { type: "ota_progress"; data: OtaProgressData }
  | { type: "ota_complete"; data: OtaCompleteData }
  | { type: "ota_error"; data: OtaErrorData };

type MessageHandler = (msg: WSMessage) => void;

/**
 * Socket lifecycle, surfaced so the UI can tell a healthy connection from a
 * device that has dropped off. Previously these transitions were logged to the
 * dev console only, leaving stale readings on screen indistinguishable from
 * live ones.
 */
export type WSConnectionState = "connecting" | "open" | "offline";

type StatusHandler = (state: WSConnectionState) => void;

const RECONNECT_DELAY_MS = 3000;

class KilnWebSocket {
  private ws: WebSocket | null = null;
  private handlers: Set<MessageHandler> = new Set();
  private reconnectTimer: number | null = null;
  private intentionalClose = false;
  private token: string | null = null;
  private statusHandlers: Set<StatusHandler> = new Set();
  private connectionState: WSConnectionState = "offline";

  private buildUrl(): string {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const base = `${protocol}//${window.location.host}/api/v1/ws`;
    return this.token ? `${base}?token=${encodeURIComponent(this.token)}` : base;
  }

  setAuthToken(token: string | null) {
    if (this.token === token) return;
    this.token = token;
    // Reconnect with the new credential if we're currently up.
    if (this.ws) {
      this.intentionalClose = true;
      this.detachHandlers(this.ws);
      this.ws.close();
      this.ws = null;
      this.intentionalClose = false;
      this.connect();
    }
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) {
      return;
    }

    this.intentionalClose = false;
    this.setConnectionState("connecting");

    try {
      const ws = new WebSocket(this.buildUrl());
      this.ws = ws;

      ws.onopen = () => {
        if (import.meta.env.DEV) console.log("[WS] Connected");
        this.setConnectionState("open");
        if (this.reconnectTimer) {
          clearTimeout(this.reconnectTimer);
          this.reconnectTimer = null;
        }
      };

      ws.onmessage = (event) => {
        try {
          const msg: WSMessage = JSON.parse(event.data);
          this.handlers.forEach((handler) => handler(msg));
        } catch (e) {
          if (import.meta.env.DEV) console.warn("[WS] Failed to parse message:", e);
        }
      };

      ws.onclose = () => {
        this.setConnectionState("offline");
        if (this.intentionalClose) return;
        if (import.meta.env.DEV) console.log("[WS] Disconnected, reconnecting...");
        this.scheduleReconnect();
      };

      ws.onerror = (err) => {
        if (import.meta.env.DEV) console.error("[WS] Error:", err);
        // Let onclose handle reconnect; closing here would double-fire.
      };
    } catch (e) {
      if (import.meta.env.DEV) console.error("[WS] Failed to connect:", e);
      this.setConnectionState("offline");
      this.scheduleReconnect();
    }
  }

  private detachHandlers(ws: WebSocket) {
    ws.onopen = null;
    ws.onmessage = null;
    ws.onclose = null;
    ws.onerror = null;
  }

  private scheduleReconnect() {
    if (this.reconnectTimer || this.intentionalClose) return;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, RECONNECT_DELAY_MS);
  }

  disconnect() {
    this.intentionalClose = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.detachHandlers(this.ws);
      this.ws.close();
      this.ws = null;
    }
    // detachHandlers() clears onclose, so the close below never reports itself —
    // set the state explicitly or it would stay stuck at "open".
    this.setConnectionState("offline");
  }

  subscribe(handler: MessageHandler): () => void {
    this.handlers.add(handler);
    return () => {
      this.handlers.delete(handler);
    };
  }

  /** Subscribe to socket lifecycle changes. Fires immediately with the current state. */
  subscribeStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    handler(this.connectionState);
    return () => {
      this.statusHandlers.delete(handler);
    };
  }

  getConnectionState(): WSConnectionState {
    return this.connectionState;
  }

  private setConnectionState(state: WSConnectionState) {
    if (this.connectionState === state) return;
    this.connectionState = state;
    this.statusHandlers.forEach((h) => h(state));
  }
}

export const kilnWS = new KilnWebSocket();
