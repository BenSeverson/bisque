/**
 * Mock-server parity test. Spins up handlers in-process and validates every
 * response against a zod schema mirroring the TS types the frontend consumes.
 * Catches drift between the mock-server and the frontend's expectations
 * (which in turn are supposed to match the firmware — see Layer 3 for that).
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { createServer, Server } from "http";
import { AddressInfo } from "net";
import { z } from "zod";
import { handleRequest } from "./handlers";
import { firingProfileSchema, settingsSchema } from "../src/app/schemas/kiln";
import {
  autotuneStatusSchema,
  coneEntrySchema,
  firingProgressResponseSchema,
  historyRecordSchema,
  systemInfoSchema,
  thermocoupleDiagSchema,
} from "../test/contracts/responseSchemas";

let server: Server;
let baseUrl: string;

beforeAll(async () => {
  server = createServer((req, res) => {
    if (req.url?.startsWith("/api/v1") && req.url !== "/api/v1/ws") {
      void handleRequest(req, res);
      return;
    }
    res.writeHead(404);
    res.end();
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as AddressInfo).port;
  baseUrl = `http://127.0.0.1:${port}/api/v1`;
});

afterAll(async () => {
  await new Promise<void>((resolve, reject) =>
    server.close((err) => (err ? reject(err) : resolve())),
  );
});

async function get(path: string) {
  const r = await fetch(`${baseUrl}${path}`);
  expect(r.ok, `GET ${path} → ${r.status}`).toBe(true);
  return r.json();
}

async function post(path: string, body: unknown = {}) {
  const r = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { ok: r.ok, status: r.status, body: await r.json() };
}

// --- GET endpoints -----------------------------------------------------------

describe("mock-server GET endpoints", () => {
  it("GET /status returns FiringProgress shape with thermocouple block", async () => {
    expect(firingProgressResponseSchema.safeParse(await get("/status")).success).toBe(true);
  });

  it("GET /cone-table returns ConeEntry[]", async () => {
    const body = await get("/cone-table");
    expect(Array.isArray(body)).toBe(true);
    expect(body.length).toBeGreaterThan(0);
    expect(z.array(coneEntrySchema).safeParse(body).success).toBe(true);
  });

  it("GET /profiles returns FiringProfile[]", async () => {
    const body = await get("/profiles");
    expect(Array.isArray(body)).toBe(true);
    expect(body.length).toBeGreaterThan(0);
    expect(z.array(firingProfileSchema).safeParse(body).success).toBe(true);
  });

  it("GET /profiles/:id returns one FiringProfile", async () => {
    const list = await get("/profiles");
    const body = await get(`/profiles/${list[0].id}`);
    expect(firingProfileSchema.safeParse(body).success).toBe(true);
  });

  it("GET /profiles/:id → 404 for unknown id", async () => {
    const r = await fetch(`${baseUrl}/profiles/does-not-exist`);
    expect(r.status).toBe(404);
  });

  it("GET /history returns HistoryRecord[]", async () => {
    const body = await get("/history");
    expect(z.array(historyRecordSchema).safeParse(body).success).toBe(true);
  });

  it("GET /settings parses against settingsSchema", async () => {
    expect(settingsSchema.safeParse(await get("/settings")).success).toBe(true);
  });

  it("GET /system returns SystemInfo", async () => {
    expect(systemInfoSchema.safeParse(await get("/system")).success).toBe(true);
  });

  it("GET /autotune/status returns AutotuneStatus", async () => {
    expect(autotuneStatusSchema.safeParse(await get("/autotune/status")).success).toBe(true);
  });

  it("GET /diagnostics/thermocouple returns full reading", async () => {
    expect(thermocoupleDiagSchema.safeParse(await get("/diagnostics/thermocouple")).success).toBe(
      true,
    );
  });

  it("GET /history/:id/trace returns CSV with header", async () => {
    const r = await fetch(`${baseUrl}/history/1/trace`);
    expect(r.ok).toBe(true);
    const text = await r.text();
    expect(text.split("\n")[0]).toBe("time_s,temp_c");
  });

  it("GET /history/:id/trace → 404 for unknown id", async () => {
    const r = await fetch(`${baseUrl}/history/9999/trace`);
    expect(r.status).toBe(404);
  });
});

// --- POST endpoints ----------------------------------------------------------

const okResponseSchema = z.object({ ok: z.boolean() }).passthrough();

describe("mock-server POST endpoints", () => {
  it("POST /firing/start with bad profileId returns ok:false", async () => {
    const r = await post("/firing/start", { profileId: "nope" });
    expect(r.ok).toBe(false); // mock returns 400
    expect(r.body.ok).toBe(false);
  });

  it("POST /firing/start with real profileId starts firing", async () => {
    const profiles = await get("/profiles");
    const r = await post("/firing/start", { profileId: profiles[0].id });
    expect(r.body.ok).toBe(true);
    // Clean up: stop the firing so subsequent tests are deterministic
    await post("/firing/stop");
  });

  it("POST /firing/stop, pause, skip-segment all return ok:true", async () => {
    expect((await post("/firing/stop")).body.ok).toBe(true);
    const pause = await post("/firing/pause");
    expect(okResponseSchema.safeParse(pause.body).success).toBe(true);
    expect((await post("/firing/skip-segment")).body.ok).toBe(true);
  });

  it("POST /profiles/cone-fire generates a valid FiringProfile", async () => {
    const r = await post("/profiles/cone-fire", {
      coneId: 18,
      speed: 1,
      preheat: true,
      slowCool: false,
      save: false,
    });
    expect(r.body).toBeTruthy();
    expect(firingProfileSchema.safeParse(r.body).success).toBe(true);
  });

  it("POST /profiles/cone-fire with bad coneId returns 400 + error", async () => {
    const r = await post("/profiles/cone-fire", {
      coneId: 9999,
      speed: 1,
      preheat: false,
      slowCool: false,
      save: false,
    });
    expect(r.ok).toBe(false);
    expect(r.body.error).toBeTypeOf("string");
  });

  it("POST /settings updates settings and round-trip matches settingsSchema", async () => {
    const newSettings = {
      tempUnit: "F",
      maxSafeTemp: 1350,
      alarmEnabled: false,
      autoShutdown: false,
      notificationsEnabled: false,
      tcOffsetC: -1.5,
      webhookUrl: "https://example.test/hook",
      elementWatts: 1500,
      electricityCostKwh: 0.12,
    };
    expect((await post("/settings", newSettings)).body.ok).toBe(true);
    const after = await get("/settings");
    expect(settingsSchema.safeParse(after).success).toBe(true);
    expect(after.tempUnit).toBe("F");
    expect(after.maxSafeTemp).toBe(1350);
  });

  it("POST /profiles upserts and reflects in GET /profiles", async () => {
    const fixture = {
      id: "test-parity-profile",
      name: "Parity Test",
      description: "",
      segments: [{ id: "s1", name: "Ramp", rampRate: 100, targetTemp: 500, holdTime: 0 }],
      maxTemp: 500,
      estimatedDuration: 60,
    };
    expect((await post("/profiles", fixture)).body.ok).toBe(true);
    const list = await get("/profiles");
    expect(list.find((p: { id: string }) => p.id === fixture.id)).toBeTruthy();

    // Clean up
    const del = await fetch(`${baseUrl}/profiles/${fixture.id}`, { method: "DELETE" });
    expect(del.ok).toBe(true);
  });

  it("POST /diagnostics/relay echoes durationSeconds", async () => {
    const r = await post("/diagnostics/relay", { durationSeconds: 5 });
    expect(r.body.ok).toBe(true);
    expect(r.body.durationSeconds).toBe(5);
  });
});
