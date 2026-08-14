import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { FiringProfile } from "../types/kiln";

/**
 * The REST client. Three things here are load-bearing and were unpinned:
 *
 * - Token persistence. The token lives in sessionStorage and is handed to the
 *   WebSocket client at module load; get that wrong and a reload either locks
 *   the user out or leaves the socket unauthenticated while REST works.
 * - Error shaping. The firmware answers a failed request with the bare message
 *   (`httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing ssid")`), no JSON
 *   envelope, and every toast in the UI is built from what `request()` throws.
 * - The hand-rolled XHR OTA upload, which is the one path where a mis-shaped
 *   branch bricks the update UX rather than showing a bad message.
 */

const setAuthToken = vi.fn();
vi.mock("./websocket", () => ({ kilnWS: { setAuthToken } }));

const TOKEN_STORAGE_KEY = "bisque.apiToken";

/** Re-import the module so its load-time sessionStorage read runs again. */
async function loadApi() {
  vi.resetModules();
  return await import("./api");
}

function jsonResponse(body: unknown, init: { status?: number } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json" },
  });
}

/** The firmware's error shape: a bare message with no JSON envelope. */
function errorResponse(status: number, message: string) {
  return new Response(message, { status });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  window.sessionStorage.clear();
  setAuthToken.mockClear();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("api: token persistence", () => {
  it("has no token on a fresh session", async () => {
    const { getApiToken } = await loadApi();
    expect(getApiToken()).toBeNull();
    // Nothing to hand the socket, so it must not be told to rotate.
    expect(setAuthToken).not.toHaveBeenCalled();
  });

  it("restores a token saved before the reload", async () => {
    // Held in sessionStorage rather than memory precisely so F5 does not lock
    // the user out of their own kiln.
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, "persisted");
    const { getApiToken } = await loadApi();
    expect(getApiToken()).toBe("persisted");
  });

  it("hands a restored token to the WebSocket client at load", async () => {
    // The socket cannot send an Authorization header, so it needs the token
    // separately. Without this the dashboard reconnect-loops on a locked kiln
    // while every REST call succeeds.
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, "persisted");
    await loadApi();
    expect(setAuthToken).toHaveBeenCalledWith("persisted");
  });

  it("persists and activates a newly set token", async () => {
    const { setApiToken, getApiToken } = await loadApi();
    setApiToken("fresh");
    expect(getApiToken()).toBe("fresh");
    expect(window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBe("fresh");
    expect(setAuthToken).toHaveBeenCalledWith("fresh");
  });

  it("erases the stored token when cleared", async () => {
    // A leftover entry would be restored on the next reload and re-authenticate
    // against a device that no longer accepts it.
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, "old");
    const { setApiToken, getApiToken } = await loadApi();
    setApiToken(null);
    expect(getApiToken()).toBeNull();
    expect(window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
    expect(setAuthToken).toHaveBeenLastCalledWith(null);
  });
});

describe("api: request()", () => {
  it("calls the versioned API base", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(jsonResponse({ isActive: false }));
    await api.getStatus();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/status");
  });

  it("sends no Authorization header when unauthenticated", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.getProfiles();
    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers).not.toHaveProperty("Authorization");
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("bearers the token on every call once one is set", async () => {
    const { api, setApiToken } = await loadApi();
    setApiToken("secret");
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.getProfiles();
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer secret");
  });

  it("stops sending the header after the token is cleared", async () => {
    const { api, setApiToken } = await loadApi();
    setApiToken("secret");
    setApiToken(null);
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.getProfiles();
    expect(fetchMock.mock.calls[0][1].headers).not.toHaveProperty("Authorization");
  });

  it("serialises the body and method of a write", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await api.startFiring("glaze-6", 30);
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ profileId: "glaze-6", delayMinutes: 30 });
  });

  it("throws the firmware's bare message, with its status", async () => {
    // The firmware sends the message with no envelope, and the UI puts what is
    // thrown straight into a toast. A wrapped body would show up braces and all.
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(errorResponse(400, "Missing ssid"));
    await expect(api.saveWifi("", "")).rejects.toThrow("API error 400: Missing ssid");
  });

  it("reports a lockout as a 401 rather than a parse failure", async () => {
    // An unauthenticated request gets an error body that is not JSON. Reading
    // it as JSON first would surface "Unexpected token" instead of the 401 that
    // tells the user their token is wrong.
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(errorResponse(401, "Unauthorized"));
    await expect(api.getProfiles()).rejects.toThrow("API error 401: Unauthorized");
  });

  it("still reports the status when the device sends an empty error body", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(errorResponse(409, ""));
    await expect(api.stopFiring()).rejects.toThrow("API error 409: ");
  });

  it("lets a transport failure through untouched", async () => {
    // Wi-Fi dropped mid-request. There is no status to report, and dressing it
    // up as an API error would blame the device for the network.
    const { api } = await loadApi();
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api.getStatus()).rejects.toThrow("Failed to fetch");
  });

  it("returns the parsed body on success", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(jsonResponse({ ok: true, id: "glaze-6" }));
    await expect(api.saveProfile({ id: "glaze-6" } as FiringProfile)).resolves.toEqual({
      ok: true,
      id: "glaze-6",
    });
  });
});

describe("api: non-JSON responses", () => {
  it("authenticates a trace download and returns the blob", async () => {
    const { api, setApiToken } = await loadApi();
    setApiToken("secret");
    fetchMock.mockResolvedValue(new Response("t,temp\n0,20\n", { status: 200 }));
    const blob = await api.getHistoryTraceBlob(3);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/history/3/trace");
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer secret");
    expect(await blob.text()).toBe("t,temp\n0,20\n");
  });

  it("shapes a failed download the same way as a JSON call", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(errorResponse(404, "No such record"));
    await expect(api.exportProfile("nope")).rejects.toThrow("API error 404: No such record");
  });

  it("returns trace text for the chart", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(new Response("t,temp\n0,20\n", { status: 200 }));
    await expect(api.getHistoryTrace(3)).resolves.toBe("t,temp\n0,20\n");
  });

  it("shapes a failed text fetch the same way", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(errorResponse(404, "No such record"));
    await expect(api.getHistoryTrace(9)).rejects.toThrow("API error 404: No such record");
  });
});

describe("api: duplicateProfile", () => {
  it("posts a copy under a new id, leaving the original alone", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(jsonResponse({ ok: true, id: "glaze-6-copy" }));
    const original = { id: "glaze-6", name: "Glaze 6", segments: [] } as unknown as FiringProfile;
    await api.duplicateProfile(original);

    const sent = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(sent.id).not.toBe("glaze-6");
    expect(sent.name).toBe("Glaze 6 (Copy)");
    // Mutating the argument would rename the row the user duplicated from.
    expect(original.name).toBe("Glaze 6");
  });
});

/* --- OTA upload -------------------------------------------------------- */

class FakeXhr {
  static last: FakeXhr | null = null;

  method = "";
  url = "";
  headers: Record<string, string> = {};
  sent: unknown = null;
  status = 200;
  responseText = "";

  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  upload: {
    onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null;
  } = { onprogress: null };

  constructor() {
    FakeXhr.last = this;
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  send(body: unknown) {
    this.sent = body;
  }

  /** Simulate the device answering. */
  respond(status: number, responseText: string) {
    this.status = status;
    this.responseText = responseText;
    this.onload?.();
  }

  fail() {
    this.onerror?.();
  }
}

function firmwareFile() {
  return new File([new Uint8Array([1, 2, 3])], "bisque.bin");
}

describe("api: uploadOta()", () => {
  beforeEach(() => {
    FakeXhr.last = null;
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
  });

  it("POSTs the raw file to /ota", async () => {
    const { api } = await loadApi();
    const file = firmwareFile();
    const promise = api.uploadOta(file);
    const xhr = FakeXhr.last!;

    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/api/v1/ota");
    // Not multipart: the firmware streams the request body straight to the OTA
    // partition, so a form wrapper would be flashed as part of the image.
    expect(xhr.sent).toBe(file);

    xhr.respond(200, JSON.stringify({ ok: true }));
    await expect(promise).resolves.toEqual({ ok: true });
  });

  it("authenticates the upload when a token is set", async () => {
    // XHR is hand-rolled here, so it does not go through authHeaders(); a
    // missing header means a 401 on a token-protected kiln.
    const { api, setApiToken } = await loadApi();
    setApiToken("secret");
    const promise = api.uploadOta(firmwareFile());
    const xhr = FakeXhr.last!;
    expect(xhr.headers.Authorization).toBe("Bearer secret");
    xhr.respond(200, JSON.stringify({ ok: true }));
    await promise;
  });

  it("sends no Authorization header when unauthenticated", async () => {
    const { api } = await loadApi();
    const promise = api.uploadOta(firmwareFile());
    const xhr = FakeXhr.last!;
    expect(xhr.headers).not.toHaveProperty("Authorization");
    xhr.respond(200, JSON.stringify({ ok: true }));
    await promise;
  });

  it("reports upload progress as a percentage", async () => {
    const { api } = await loadApi();
    const onProgress = vi.fn();
    const promise = api.uploadOta(firmwareFile(), onProgress);
    const xhr = FakeXhr.last!;

    xhr.upload.onprogress!({ lengthComputable: true, loaded: 50, total: 200 });
    xhr.upload.onprogress!({ lengthComputable: true, loaded: 200, total: 200 });
    expect(onProgress.mock.calls.map((c) => c[0])).toEqual([25, 100]);

    xhr.respond(200, JSON.stringify({ ok: true }));
    await promise;
  });

  it("ignores a progress event with no known total", async () => {
    // loaded/total is NaN when the length is unknown, which would render as
    // "NaN%" in the progress bar.
    const { api } = await loadApi();
    const onProgress = vi.fn();
    const promise = api.uploadOta(firmwareFile(), onProgress);
    const xhr = FakeXhr.last!;

    xhr.upload.onprogress!({ lengthComputable: false, loaded: 50, total: 0 });
    expect(onProgress).not.toHaveBeenCalled();

    xhr.respond(200, JSON.stringify({ ok: true }));
    await promise;
  });

  it("attaches no progress handler when the caller does not want one", async () => {
    const { api } = await loadApi();
    const promise = api.uploadOta(firmwareFile());
    expect(FakeXhr.last!.upload.onprogress).toBeNull();
    FakeXhr.last!.respond(200, JSON.stringify({ ok: true }));
    await promise;
  });

  it("rejects with the device's message on a rejected image", async () => {
    // The firmware answers 400 with why it refused (bad magic byte, wrong
    // chip); that string is the only diagnosis the user gets.
    const { api } = await loadApi();
    const promise = api.uploadOta(firmwareFile());
    FakeXhr.last!.respond(400, "Invalid image header");
    await expect(promise).rejects.toThrow("OTA error 400: Invalid image header");
  });

  it("rejects rather than hanging when a 2xx body is not JSON (#135)", async () => {
    // A captive portal or an interposing proxy page. JSON.parse used to throw
    // synchronously out of onload, so neither settler ran and the caller
    // awaited forever with the UI stuck at "Uploading firmware...".
    const { api } = await loadApi();
    const promise = api.uploadOta(firmwareFile());
    FakeXhr.last!.respond(200, "<html>Sign in to continue</html>");
    await expect(promise).rejects.toThrow(/non-JSON response/);
  });

  it("rejects when the connection drops mid-upload", async () => {
    // The controller reboots partway through a flash; onload never fires.
    const { api } = await loadApi();
    const promise = api.uploadOta(firmwareFile());
    FakeXhr.last!.fail();
    await expect(promise).rejects.toThrow("OTA upload failed");
  });

  it("treats a 3xx as a failure", async () => {
    // A redirect means something other than the kiln answered; following it
    // would report success for an image that was never flashed.
    const { api } = await loadApi();
    const promise = api.uploadOta(firmwareFile());
    FakeXhr.last!.respond(302, "");
    await expect(promise).rejects.toThrow("OTA error 302: ");
  });
});

describe("api: rollbackOta()", () => {
  it("reports a dropped connection as unacknowledged rather than failed", async () => {
    // handle_ota_rollback() calls
    // esp_ota_mark_app_invalid_rollback_and_reboot(), so the socket usually
    // dies before the reply lands. Rejecting would tell the user the rollback
    // failed while the kiln was busy performing it — but the same TypeError
    // arrives when the kiln was already unreachable and never got the POST,
    // and the Fetch spec gives no way to tell those apart. So it resolves
    // without claiming the request landed, and the caller words it honestly.
    const { api } = await loadApi();
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api.rollbackOta()).resolves.toEqual({ acknowledged: false });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/ota/rollback");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
  });

  it("acknowledges a rollback the controller answered before rebooting", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await expect(api.rollbackOta()).resolves.toEqual({ acknowledged: true });
  });

  it("refuses to credit a 2xx that did not come from the kiln", async () => {
    // A captive portal, a proxy, or whatever picked up the kiln's DHCP lease
    // while the tab sat open all answer 200. Reporting "rolling back" off the
    // status code alone would credit them with a reboot that never happened.
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(
      new Response("<html>Sign in to the network</html>", { status: 200 }),
    );
    await expect(api.rollbackOta()).rejects.toThrow(/did not come from the kiln/);
  });

  it("refuses a 2xx whose body is JSON but not the kiln's answer", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(jsonResponse({ status: "captive" }));
    await expect(api.rollbackOta()).rejects.toThrow(/did not come from the kiln/);
  });

  it("does not follow a redirect away from the kiln", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await api.rollbackOta();
    expect(fetchMock.mock.calls[0][1].redirect).toBe("manual");
  });

  it("names a redirect for what it is instead of blaming the reboot", async () => {
    // `redirect: "error"` would reject here, and a rejection means "the kiln
    // stopped answering, expected while it reboots" — a sentence about a kiln
    // that was never reached. An opaque response falls through to the error
    // that describes what actually happened.
    const { api } = await loadApi();
    const opaque = new Response(null, { status: 200 });
    Object.defineProperty(opaque, "type", { value: "opaqueredirect" });
    fetchMock.mockResolvedValue(opaque);
    await expect(api.rollbackOta()).rejects.toThrow(/answered by a redirect/);
  });

  it("still reports an outright refusal", async () => {
    // 400 with no image behind the running one, 409 while a firing runs. Both
    // arrive intact — the device is very much still up — and both mean the
    // firmware did not change.
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(errorResponse(400, "Rollback not available"));
    await expect(api.rollbackOta()).rejects.toThrow("API error 400: Rollback not available");
  });

  it("bearers the token, since the endpoint is authenticated", async () => {
    const { api, setApiToken } = await loadApi();
    setApiToken("secret");
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await api.rollbackOta();
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer secret");
  });
});
