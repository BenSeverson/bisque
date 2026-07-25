import type { Plugin } from "vite";
import type { IncomingMessage } from "http";
import type { Duplex } from "stream";
import { WebSocketServer } from "ws";
import { handleRequest } from "./handlers";
import { state } from "./state";
import { ensureTicking } from "./simulator";

/** Request path with any query string stripped. `undefined` stays undefined. */
function pathOf(url: string | undefined): string | undefined {
  return url?.split("?")[0];
}

export function kilnMockPlugin(): Plugin {
  return {
    name: "kiln-mock",
    configureServer(server) {
      if (process.env.VITE_MOCK === "false") return;

      const speedStr = process.env.VITE_MOCK_SPEED || "60";
      console.log(`\n  Mock kiln server enabled (${speedStr}x speed)\n`);

      state.speed = parseInt(speedStr, 10);

      const wss = new WebSocketServer({ noServer: true });
      state.wss = wss;

      // Forward simulator broadcasts to every connected WS client.
      state.subscribers.add((msg) => {
        for (const client of wss.clients) {
          if (client.readyState === 1 /* OPEN */) client.send(msg);
        }
      });

      wss.on("connection", (ws) => {
        console.log("[mock] WebSocket client connected");
        // Match the firmware: telemetry flows continuously once a client is
        // listening, not only while a firing is running.
        ensureTicking();
        ws.on("close", () => console.log("[mock] WebSocket client disconnected"));
      });

      // Intercept WebSocket upgrades for /api/v1/ws before the proxy can handle them.
      // We override emit so the proxy's upgrade listener never fires for our URL.
      const httpServer = server.httpServer;
      if (httpServer) {
        const originalEmit = httpServer.emit.bind(httpServer);
        const patchable = httpServer as unknown as { emit: typeof originalEmit };
        patchable.emit = function (event: string | symbol, ...args: unknown[]): boolean {
          if (event === "upgrade") {
            const req = args[0] as IncomingMessage;
            // Compare the path only. The client appends ?token=... whenever an
            // API token is set, and an exact match let those upgrades fall
            // through to the hardware proxy while REST kept hitting the mock.
            if (pathOf(req.url) === "/api/v1/ws") {
              const socket = args[1] as Duplex;
              const head = args[2] as Buffer;
              wss.handleUpgrade(req, socket, head, (ws) => {
                wss.emit("connection", ws, req);
              });
              return true;
            }
          }
          return originalEmit(event, ...args);
        };
      }

      // Intercept REST requests before the proxy middleware
      server.middlewares.use((req, res, next) => {
        if (!req.url?.startsWith("/api/v1") || pathOf(req.url) === "/api/v1/ws") {
          return next();
        }
        handleRequest(req, res);
      });
    },
  };
}
