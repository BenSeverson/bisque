import type { Plugin } from 'vite';
import type { IncomingMessage } from 'http';
import type { Duplex } from 'stream';
import { WebSocketServer } from 'ws';
import { handleRequest } from './handlers';
import { state } from './state';

export function kilnMockPlugin(): Plugin {
  return {
    name: 'kiln-mock',
    configureServer(server) {
      if (process.env.VITE_MOCK === 'false') return;

      const speedStr = process.env.VITE_MOCK_SPEED || '60';
      console.log(`\n  Mock kiln server enabled (${speedStr}x speed)\n`);

      const wss = new WebSocketServer({ noServer: true });
      state.wss = wss;

      wss.on('connection', (ws) => {
        console.log('[mock] WebSocket client connected');
        ws.on('close', () =>
          console.log('[mock] WebSocket client disconnected'),
        );
      });

      // Intercept WebSocket upgrades for /api/v1/ws before the proxy can handle them.
      // We override emit so the proxy's upgrade listener never fires for our URL.
      const httpServer = server.httpServer;
      if (httpServer) {
        const originalEmit = httpServer.emit.bind(httpServer);
        (httpServer as any).emit = function (
          event: string,
          ...args: any[]
        ): boolean {
          if (event === 'upgrade') {
            const req = args[0] as IncomingMessage;
            if (req.url === '/api/v1/ws') {
              const socket = args[1] as Duplex;
              const head = args[2] as Buffer;
              wss.handleUpgrade(req, socket, head, (ws) => {
                wss.emit('connection', ws, req);
              });
              return true;
            }
          }
          return originalEmit(event, ...args);
        };
      }

      // Intercept REST requests before the proxy middleware
      server.middlewares.use((req, res, next) => {
        if (!req.url?.startsWith('/api/v1') || req.url === '/api/v1/ws') {
          return next();
        }
        handleRequest(req, res);
      });
    },
  };
}
