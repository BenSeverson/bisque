/**
 * Unit test for the transport-agnostic router (`dispatch`). The HTTP-level
 * parity test lives in handlers.test.ts; this one exercises dispatch() directly
 * — status codes, content types, and the download headers that the browser
 * demo relies on. Kept timer-free (no firing/autotune starts) so it leaves no
 * open handles.
 */
import { describe, it, expect } from "vitest";
import { dispatch } from "./router";

describe("dispatch() router", () => {
  it("GET /status returns a JSON body", () => {
    const r = dispatch("GET", "/status", {});
    expect(r.status).toBe(200);
    expect(r.json).toBeTruthy();
  });

  it("GET /cone-table returns a non-empty array", () => {
    const r = dispatch("GET", "/cone-table", {});
    expect(r.status).toBe(200);
    expect(Array.isArray(r.json)).toBe(true);
    expect((r.json as unknown[]).length).toBeGreaterThan(0);
  });

  it("GET /profiles/:id/export sets a download Content-Disposition header", () => {
    const list = dispatch("GET", "/profiles", {}).json as Array<{ id: string }>;
    const r = dispatch("GET", `/profiles/${list[0].id}/export`, {});
    expect(r.status).toBe(200);
    expect(r.contentType).toBe("application/json");
    expect(r.text).toContain(list[0].id);
    expect(r.headers?.["Content-Disposition"]).toContain(".json");
  });

  it("GET /history/:id/trace returns CSV text with the expected header", () => {
    const r = dispatch("GET", "/history/1/trace", {});
    expect(r.status).toBe(200);
    expect(r.contentType).toBe("text/csv");
    expect(r.text?.split("\n")[0]).toBe("time_s,temp_c");
  });

  it("POST /firing/start with an unknown profile returns 400 + ok:false", () => {
    const r = dispatch("POST", "/firing/start", { profileId: "does-not-exist" });
    expect(r.status).toBe(400);
    expect((r.json as { ok: boolean }).ok).toBe(false);
  });

  it("POST /settings persists and round-trips via GET /settings", () => {
    dispatch("POST", "/settings", { maxSafeTemp: 1234 });
    const after = dispatch("GET", "/settings", {}).json as { maxSafeTemp: number };
    expect(after.maxSafeTemp).toBe(1234);
  });

  it("unknown route returns 404", () => {
    const r = dispatch("GET", "/nope", {});
    expect(r.status).toBe(404);
  });
});
