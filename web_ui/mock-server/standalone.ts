/**
 * Standalone mock kiln server for iOS simulator testing.
 *
 * Usage:
 *   cd web_ui && npm run mock-server
 *   # or: npx tsx mock-server/standalone.ts
 *
 * The iOS app can then connect to localhost:8080 (or MOCK_PORT).
 */
import { createServer } from 'http';
import { WebSocketServer } from 'ws';
import { handleRequest } from './handlers';
import { state } from './state';

const port = parseInt(process.env.MOCK_PORT || '8080', 10);
const speed = process.env.MOCK_SPEED || '60';

// Set VITE_MOCK_SPEED so the simulator module picks it up
process.env.VITE_MOCK_SPEED = speed;

const server = createServer((req, res) => {
  // CORS headers for local development
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.url?.startsWith('/api/v1') && req.url !== '/api/v1/ws') {
    handleRequest(req, res);
    return;
  }

  // Health check at root
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ mock: true, status: 'running' }));
});

const wss = new WebSocketServer({ noServer: true });
state.wss = wss;

wss.on('connection', (ws) => {
  console.log('[mock] WebSocket client connected');
  ws.on('close', () => console.log('[mock] WebSocket client disconnected'));
});

server.on('upgrade', (req, socket, head) => {
  if (req.url === '/api/v1/ws') {
    wss.handleUpgrade(req, socket, head, (ws) => {
      wss.emit('connection', ws, req);
    });
  } else {
    socket.destroy();
  }
});

server.listen(port, () => {
  console.log(`\n  Mock kiln server running on http://localhost:${port}`);
  console.log(`  WebSocket endpoint: ws://localhost:${port}/api/v1/ws`);
  console.log(`  Simulation speed: ${speed}x\n`);
  console.log(`  Connect the iOS simulator to: localhost  port: ${port}\n`);
});
