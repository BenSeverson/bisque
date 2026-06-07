/**
 * Node HTTP adapter over the transport-agnostic router (`./router`).
 *
 * This is the only Node-coupled piece of the mock: it parses an
 * `IncomingMessage` and writes a `ServerResponse`, delegating all routing and
 * simulation to `dispatch()`. Used by the Vite dev plugin and the standalone
 * iOS mock server. The browser demo bypasses this file entirely and calls
 * `dispatch()` directly.
 */
import type { IncomingMessage, ServerResponse } from 'http';
import { dispatch } from './router';

function parseBody(req: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk: Buffer) => {
      body += chunk.toString();
    });
    req.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch {
        reject(new Error('Invalid JSON'));
      }
    });
  });
}

export async function handleRequest(
  req: IncomingMessage,
  res: ServerResponse,
): Promise<void> {
  const method = req.method || 'GET';
  const url = req.url || '';
  const apiPath = url.split('?')[0].replace('/api/v1', '');

  try {
    const body = method === 'POST' ? await parseBody(req) : {};
    const result = dispatch(method, apiPath, body);
    const headers: Record<string, string> = { ...(result.headers ?? {}) };
    if (result.text !== undefined) {
      headers['Content-Type'] = result.contentType ?? 'text/plain';
      res.writeHead(result.status, headers);
      res.end(result.text);
    } else {
      headers['Content-Type'] = result.contentType ?? 'application/json';
      res.writeHead(result.status, headers);
      res.end(JSON.stringify(result.json ?? null));
    }
  } catch (err) {
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: (err as Error).message }));
  }
}
