/**
 * Integration test for the demo transport: after installDemo() patches
 * window.fetch and window.WebSocket, the app's normal HTTP + WebSocket calls
 * must be served by the in-browser simulator. This is the automated stand-in
 * for the manual browser smoke test of the GitHub Pages demo.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { installDemo } from "./installDemo";
import { mockProfiles } from "../data/mockProfiles";

beforeAll(() => {
  installDemo();
});

describe("installDemo transport", () => {
  it("routes GET /api/v1/status through the simulator", async () => {
    const res = await window.fetch("/api/v1/status");
    expect(res.ok).toBe(true);
    const body = await res.json();
    expect(typeof body.status).toBe("string");
    expect(body).toHaveProperty("currentTemp");
  });

  it("serves /api/v1/profiles as a non-empty array", async () => {
    const res = await window.fetch("/api/v1/profiles");
    const body = await res.json();
    expect(Array.isArray(body)).toBe(true);
    expect(body.length).toBeGreaterThan(0);
  });

  it("handles a POST JSON body (settings round-trip)", async () => {
    await window.fetch("/api/v1/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ maxSafeTemp: 1299 }),
    });
    const res = await window.fetch("/api/v1/settings");
    const body = await res.json();
    expect(body.maxSafeTemp).toBe(1299);
  });

  it("returns the CSV history trace with the right content type", async () => {
    const res = await window.fetch("/api/v1/history/1/trace");
    expect(res.headers.get("Content-Type")).toContain("text/csv");
    const text = await res.text();
    expect(text.split("\n")[0]).toBe("time_s,temp_c");
  });

  it("emits temp_update over the fake WebSocket once a firing starts", async () => {
    const ws = new window.WebSocket("ws://localhost/api/v1/ws");
    const message = await new Promise<{ type: string; data: { currentTemp: number } }>(
      (resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("no temp_update received")), 4000);
        ws.onopen = () => {
          // Start a firing so the simulator begins broadcasting.
          void window.fetch("/api/v1/firing/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ profileId: mockProfiles[0].id }),
          });
        };
        ws.onmessage = (ev: MessageEvent) => {
          clearTimeout(timer);
          resolve(JSON.parse(ev.data));
        };
      },
    );
    expect(message.type).toBe("temp_update");
    expect(message.data).toHaveProperty("currentTemp");

    ws.close();
    await window.fetch("/api/v1/firing/stop", { method: "POST" });
  });
});
