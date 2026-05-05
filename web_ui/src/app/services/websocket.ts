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

export interface WSMessage {
  type: "temp_update";
  data: TempUpdateData;
}

type MessageHandler = (msg: WSMessage) => void;

const RECONNECT_DELAY_MS = 3000;

class KilnWebSocket {
  private ws: WebSocket | null = null;
  private handlers: Set<MessageHandler> = new Set();
  private reconnectTimer: number | null = null;
  private intentionalClose = false;
  private token: string | null = null;

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

    try {
      const ws = new WebSocket(this.buildUrl());
      this.ws = ws;

      ws.onopen = () => {
        if (import.meta.env.DEV) console.log("[WS] Connected");
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
  }

  subscribe(handler: MessageHandler): () => void {
    this.handlers.add(handler);
    return () => {
      this.handlers.delete(handler);
    };
  }
}

export const kilnWS = new KilnWebSocket();
