import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { KilnSettings } from "../types/kiln";
import type { OtaStatus } from "../schemas/api";
import type { WSMessage } from "../schemas/ws";
import { withQueryClient } from "../test/queryWrapper";

/**
 * Settings is where every irreversible thing in the UI lives: setting and
 * clearing the API token (the one action that can lock the user out of their
 * own kiln), forgetting Wi-Fi credentials, pulsing the relay, restarting the
 * controller, and both firmware-update paths.
 *
 * What is asserted here is the *outcome reporting* — which request went out,
 * in what order, and what the user is told afterwards. Those are the branches
 * where a bug is silent: a failed save that toasts success, a local token
 * adopted before the device stored it, a progress bar that never clears.
 */

const toastFns = {
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
};
vi.mock("sonner", () => ({ toast: toastFns }));

const setApiToken = vi.fn();
const apiMock = {
  getSettings: vi.fn(),
  saveSettings: vi.fn(),
  getSystemInfo: vi.fn(),
  getAutotuneStatus: vi.fn(),
  startAutotune: vi.fn(),
  stopAutotune: vi.fn(),
  getPidGains: vi.fn(),
  savePidGains: vi.fn(),
  getThermocoupleDiag: vi.fn(),
  testRelay: vi.fn(),
  reboot: vi.fn(),
  uploadOta: vi.fn(),
  checkOta: vi.fn(),
  installOta: vi.fn(),
  otaStatus: vi.fn(),
  rollbackOta: vi.fn(),
  confirmOta: vi.fn(),
  getWifi: vi.fn(),
  saveWifi: vi.fn(),
  clearWifi: vi.fn(),
};
vi.mock("../services/api", () => ({
  api: apiMock,
  setApiToken,
  getApiToken: () => null,
}));

/** The OTA install progress stream. Tests push frames through `pushFrame`. */
let wsSubscribers: ((msg: WSMessage) => void)[] = [];
vi.mock("../services/websocket", () => ({
  kilnWS: {
    connect: vi.fn(),
    disconnect: vi.fn(),
    setAuthToken: vi.fn(),
    subscribeStatus: () => () => {},
    subscribe: (handler: (msg: WSMessage) => void) => {
      wsSubscribers.push(handler);
      return () => {
        wsSubscribers = wsSubscribers.filter((h) => h !== handler);
      };
    },
  },
}));

const { Settings } = await import("./Settings");
const { DEFAULT_SETTINGS } = await import("../hooks/queries");
const { useKilnStore } = await import("../stores/kilnStore");

function pushFrame(msg: WSMessage) {
  wsSubscribers.forEach((h) => h(msg));
}

function settings(overrides: Partial<KilnSettings> = {}): KilnSettings {
  return { ...DEFAULT_SETTINGS, ...overrides };
}

const systemInfo = {
  firmware: "1.4.0",
  idfVersion: "v5.3",
  uptimeSeconds: 3600,
  freeHeap: 120_000,
  freeInternalHeap: 32_000,
  elementHoursS: 7200,
  spiffsUsed: 100_000,
  spiffsTotal: 1_000_000,
  lastErrorCode: 0,
  emergencyStop: false,
  boardTempC: 30,
};

function otaStatus(overrides: Partial<OtaStatus> = {}): OtaStatus {
  return {
    running: {
      label: "ota_0",
      address: 0x110000,
      size: 0x500000,
      state: "valid",
      version: "1.4.0",
    },
    nextUpdate: { label: "ota_1", size: 0x500000 },
    bootPartition: "ota_0",
    pendingVerify: false,
    rollbackAvailable: true,
    ...overrides,
  };
}

const wifiInfo = {
  connected: true,
  apMode: false,
  ip: "192.168.1.50",
  hasSavedCredentials: true,
  savedSsid: "Studio",
};

function renderSettings() {
  const { wrapper: Wrapper } = withQueryClient();
  return render(<Settings />, { wrapper: Wrapper });
}

/** Wait for the settings query to land, so the form has real defaults. */
async function renderSettled() {
  const utils = renderSettings();
  await screen.findByText("Kiln Settings");
  await waitFor(() => expect(apiMock.getSettings).toHaveBeenCalled());
  return utils;
}

beforeEach(() => {
  vi.clearAllMocks();
  wsSubscribers = [];
  useKilnStore.setState({
    firingProgress: { ...useKilnStore.getState().firingProgress, isActive: false },
    statusObserved: false,
  });

  apiMock.getSettings.mockResolvedValue(settings());
  apiMock.saveSettings.mockResolvedValue({ ok: true });
  apiMock.getSystemInfo.mockResolvedValue(systemInfo);
  apiMock.getAutotuneStatus.mockResolvedValue({ state: "idle" });
  apiMock.getPidGains.mockResolvedValue({
    kp: 1,
    ki: 0.1,
    kd: 0.01,
    defaults: { kp: 2, ki: 0.2, kd: 0.02 },
    limits: { min: 0, max: 100 },
  });
  apiMock.getWifi.mockResolvedValue(wifiInfo);
  apiMock.otaStatus.mockResolvedValue(otaStatus());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Settings: API token (#lockout)", () => {
  it("saves the token to the device before adopting it locally", async () => {
    // The save is authenticated with the token the client is *currently* using.
    // Adopting first authenticates the save with a token the device has never
    // stored, takes a 401, and leaves the client permanently locked out.
    const order: string[] = [];
    apiMock.saveSettings.mockImplementation(async () => {
      order.push("save");
      return { ok: true };
    });
    setApiToken.mockImplementation(() => order.push("activate"));

    const user = userEvent.setup();
    await renderSettled();

    await user.type(screen.getByPlaceholderText("Enter new token..."), "hunter2");
    await user.click(screen.getByRole("button", { name: "Set Token" }));

    await waitFor(() => expect(setApiToken).toHaveBeenCalledWith("hunter2"));
    expect(order).toEqual(["save", "activate"]);
    expect(apiMock.saveSettings.mock.calls[0][0]).toMatchObject({ apiToken: "hunter2" });
    expect(toastFns.success).toHaveBeenCalledWith("API token set");
  });

  it("does not adopt a token the device refused, and says so", async () => {
    // The previous fire-and-forget mutate() toasted success even when the save
    // 401'd, hiding the lockout behind a green tick.
    apiMock.saveSettings.mockRejectedValue(new Error("API error 401: Unauthorized"));

    const user = userEvent.setup();
    await renderSettled();

    await user.type(screen.getByPlaceholderText("Enter new token..."), "hunter2");
    await user.click(screen.getByRole("button", { name: "Set Token" }));

    await waitFor(() => expect(toastFns.error).toHaveBeenCalled());
    expect(setApiToken).not.toHaveBeenCalled();
    expect(toastFns.error.mock.calls[0][0]).toContain("401");
    expect(toastFns.success).not.toHaveBeenCalledWith("API token set");
  });

  it("keeps the typed token in the field when the save fails", async () => {
    // It is the only copy the user has; clearing it on failure means retyping.
    apiMock.saveSettings.mockRejectedValue(new Error("API error 401: Unauthorized"));
    const user = userEvent.setup();
    await renderSettled();

    const field = screen.getByPlaceholderText("Enter new token...");
    await user.type(field, "hunter2");
    await user.click(screen.getByRole("button", { name: "Set Token" }));

    await waitFor(() => expect(toastFns.error).toHaveBeenCalled());
    expect(field).toHaveValue("hunter2");
  });

  it("clears the field after a token is accepted", async () => {
    const user = userEvent.setup();
    await renderSettled();

    const field = screen.getByPlaceholderText("Enter new token...");
    await user.type(field, "hunter2");
    await user.click(screen.getByRole("button", { name: "Set Token" }));

    await waitFor(() => expect(field).toHaveValue(""));
  });

  it("refuses to submit an empty token", async () => {
    const user = userEvent.setup();
    await renderSettled();

    const button = screen.getByRole("button", { name: "Set Token" });
    expect(button).toBeDisabled();
    await user.type(screen.getByPlaceholderText("Enter new token..."), "   ");
    // Whitespace is not a token; sending it would set an unusable credential.
    expect(button).toBeDisabled();
  });

  it("caps the field at the length the firmware can store", async () => {
    // kiln_settings_t.api_token is char[64]. A longer value is rejected
    // outright rather than truncated, which would leave the client
    // authenticating with a string the device never held.
    await renderSettled();
    expect(screen.getByPlaceholderText("Enter new token...")).toHaveAttribute("maxlength", "63");
  });

  it("offers Clear only once a token is set", async () => {
    apiMock.getSettings.mockResolvedValue(settings({ apiTokenSet: false }));
    await renderSettled();
    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
  });

  it("sends an explicit empty token when clearing", async () => {
    // The firmware distinguishes "" (clear it) from an omitted field (leave
    // unchanged), so a clear that omits the key silently does nothing.
    apiMock.getSettings.mockResolvedValue(settings({ apiTokenSet: true }));
    const user = userEvent.setup();
    await renderSettled();

    await user.click(await screen.findByRole("button", { name: "Clear" }));

    await waitFor(() => expect(apiMock.saveSettings).toHaveBeenCalled());
    expect(apiMock.saveSettings.mock.calls[0][0]).toMatchObject({
      apiToken: "",
      apiTokenSet: false,
    });
    await waitFor(() => expect(setApiToken).toHaveBeenCalledWith(null));
  });

  it("keeps using the old token when the clear is refused", async () => {
    apiMock.getSettings.mockResolvedValue(settings({ apiTokenSet: true }));
    apiMock.saveSettings.mockRejectedValue(new Error("API error 409: Firing in progress"));
    const user = userEvent.setup();
    await renderSettled();

    await user.click(await screen.findByRole("button", { name: "Clear" }));

    await waitFor(() => expect(toastFns.error).toHaveBeenCalled());
    expect(setApiToken).not.toHaveBeenCalled();
  });
});

describe("Settings: relay test", () => {
  it("pulses the relay for the requested duration", async () => {
    apiMock.testRelay.mockResolvedValue({ ok: true, durationSeconds: 5 });
    const user = userEvent.setup();
    await renderSettled();

    const duration = screen.getByLabelText("Pulse (s)");
    await user.clear(duration);
    await user.type(duration, "5");
    await user.click(screen.getByRole("button", { name: /Test Relay/ }));

    await waitFor(() => expect(apiMock.testRelay).toHaveBeenCalledWith(5));
  });

  it("reports the duration the controller echoes, not the one asked for", async () => {
    // handle_diag_relay() clamps silently, so its answer is the only honest
    // number. Reading the field back instead would report a pulse length the
    // SSR never held.
    apiMock.testRelay.mockResolvedValue({ ok: true, durationSeconds: 3 });
    const user = userEvent.setup();
    await renderSettled();

    const duration = screen.getByLabelText("Pulse (s)");
    await user.clear(duration);
    await user.type(duration, "5");
    await user.click(screen.getByRole("button", { name: /Test Relay/ }));

    await waitFor(() =>
      expect(toastFns.success).toHaveBeenCalledWith("Relay activated for 3 seconds"),
    );
  });

  it("refuses a duration past the firmware's clamp before energising anything", async () => {
    // The clamp is silent: 30 s comes back as 10 s with a 200. Rejecting here
    // means the number in the field is the number the SSR closes for.
    const user = userEvent.setup();
    await renderSettled();

    const duration = screen.getByLabelText("Pulse (s)");
    await user.clear(duration);
    await user.type(duration, "30");
    await user.click(screen.getByRole("button", { name: /Test Relay/ }));

    await waitFor(() => expect(toastFns.error).toHaveBeenCalled());
    expect(apiMock.testRelay).not.toHaveBeenCalled();
  });

  it("rejects a fractional duration before energising anything", async () => {
    // The element is being switched on for real; a request the firmware would
    // round is not worth sending.
    const user = userEvent.setup();
    await renderSettled();

    const duration = screen.getByLabelText("Pulse (s)");
    await user.clear(duration);
    await user.type(duration, "1.9");
    await user.click(screen.getByRole("button", { name: /Test Relay/ }));

    await waitFor(() => expect(toastFns.error).toHaveBeenCalled());
    expect(apiMock.testRelay).not.toHaveBeenCalled();
  });

  it("surfaces a refusal from the controller", async () => {
    // 409 while a firing, a delayed start, or another relay test holds the SSR.
    apiMock.testRelay.mockRejectedValue(new Error("API error 409: Firing in progress"));
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: /Test Relay/ }));

    await waitFor(() => expect(toastFns.error).toHaveBeenCalled());
    expect(toastFns.error.mock.calls[0][0]).toContain("409");
    expect(toastFns.success).not.toHaveBeenCalled();
  });
});

describe("Settings: restart", () => {
  it("asks before rebooting", async () => {
    // A restart drops the connection and aborts nothing gracefully; a stray
    // click on a toolbar button must not be enough to trigger it.
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: "Restart" }));
    expect(apiMock.reboot).not.toHaveBeenCalled();
    expect(await screen.findByText("Restart the controller?")).toBeInTheDocument();
  });

  it("does nothing when the confirmation is dismissed", async () => {
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: "Restart" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(apiMock.reboot).not.toHaveBeenCalled();
  });

  it("reboots once confirmed", async () => {
    apiMock.reboot.mockResolvedValue({ ok: true, message: "Restarting" });
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: "Restart" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Restart" }));

    await waitFor(() => expect(apiMock.reboot).toHaveBeenCalled());
    expect(toastFns.success).toHaveBeenCalledWith(expect.stringContaining("Restarting"));
  });

  it("reports a refusal rather than leaving the page waiting for a reboot", async () => {
    // handle_reboot() answers 409 while a firing or relay test is running.
    apiMock.reboot.mockRejectedValue(new Error("API error 409: Firing in progress"));
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: "Restart" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Restart" }));

    await waitFor(() => expect(toastFns.error).toHaveBeenCalled());
    expect(toastFns.error.mock.calls[0][0]).toContain("Restart refused");
  });

  it("is unavailable while the kiln is firing", async () => {
    useKilnStore.setState({
      firingProgress: { ...useKilnStore.getState().firingProgress, isActive: true },
    });
    await renderSettled();
    expect(screen.getByRole("button", { name: "Restart" })).toBeDisabled();
  });
});

describe("Settings: firmware update over the air", () => {
  it("says so when the controller is already current", async () => {
    apiMock.checkOta.mockResolvedValue({
      updateAvailable: false,
      current: "1.4.0",
      latest: "1.4.0",
    });
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: /Check for Updates/ }));

    await waitFor(() =>
      expect(toastFns.success).toHaveBeenCalledWith("You're on the latest version (1.4.0)"),
    );
    // No Install button, so there is nothing to click that would reflash the
    // same version.
    expect(screen.queryByRole("button", { name: /^Install/ })).not.toBeInTheDocument();
  });

  it("offers the newer version by name once one is found", async () => {
    apiMock.checkOta.mockResolvedValue({
      updateAvailable: true,
      current: "1.4.0",
      latest: "1.5.0",
    });
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: /Check for Updates/ }));
    expect(await screen.findByRole("button", { name: /Install 1\.5\.0/ })).toBeInTheDocument();
  });

  it("surfaces a failed update check", async () => {
    // No network path to GitHub is the common case, and it is indistinguishable
    // from "up to date" unless it is reported.
    apiMock.checkOta.mockRejectedValue(new Error("API error 500: DNS failure"));
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: /Check for Updates/ }));

    await waitFor(() => expect(toastFns.error).toHaveBeenCalled());
    expect(toastFns.error.mock.calls[0][0]).toContain("Update check failed");
  });

  it("streams install progress from the WebSocket", async () => {
    // The install runs on the device; HTTP returns as soon as it is queued, so
    // the only progress signal is the frame stream.
    apiMock.checkOta.mockResolvedValue({
      updateAvailable: true,
      current: "1.4.0",
      latest: "1.5.0",
    });
    apiMock.installOta.mockResolvedValue({ ok: true, version: "1.5.0", message: "started" });
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: /Check for Updates/ }));
    await user.click(await screen.findByRole("button", { name: /Install 1\.5\.0/ }));

    await waitFor(() => expect(apiMock.installOta).toHaveBeenCalled());
    await waitFor(() => expect(wsSubscribers.length).toBeGreaterThan(0));

    pushFrame({ type: "ota_progress", data: { phase: "download", percent: 40 } });
    expect(await screen.findByText("40%")).toBeInTheDocument();

    pushFrame({ type: "ota_complete", data: { percent: 100 } });
    await waitFor(() =>
      expect(toastFns.success).toHaveBeenCalledWith("Update installed — controller is rebooting"),
    );
  });

  it("clears the progress bar and re-enables Install when the device reports a failure", async () => {
    // A stuck bar is the worst outcome here: it tells the user an update is
    // still running on a controller that has already given up, and they wait
    // instead of retrying.
    apiMock.checkOta.mockResolvedValue({
      updateAvailable: true,
      current: "1.4.0",
      latest: "1.5.0",
    });
    apiMock.installOta.mockResolvedValue({ ok: true, version: "1.5.0", message: "started" });
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: /Check for Updates/ }));
    await user.click(await screen.findByRole("button", { name: /Install 1\.5\.0/ }));
    await waitFor(() => expect(wsSubscribers.length).toBeGreaterThan(0));

    pushFrame({ type: "ota_progress", data: { phase: "flash", percent: 70 } });
    expect(await screen.findByText("70%")).toBeInTheDocument();

    pushFrame({ type: "ota_error", data: { message: "Image validation failed" } });

    await waitFor(() =>
      expect(toastFns.error).toHaveBeenCalledWith("Update failed: Image validation failed"),
    );
    await waitFor(() => expect(screen.queryByText("Installing update...")).not.toBeInTheDocument());
    expect(await screen.findByRole("button", { name: /Install 1\.5\.0/ })).toBeEnabled();
  });

  it("recovers when the install request itself is refused", async () => {
    // Updates are blocked while a firing is active; the device answers 409
    // before any frame is emitted.
    apiMock.checkOta.mockResolvedValue({
      updateAvailable: true,
      current: "1.4.0",
      latest: "1.5.0",
    });
    apiMock.installOta.mockRejectedValue(new Error("API error 409: Firing in progress"));
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: /Check for Updates/ }));
    await user.click(await screen.findByRole("button", { name: /Install 1\.5\.0/ }));

    await waitFor(() => expect(toastFns.error).toHaveBeenCalled());
    expect(toastFns.error.mock.calls[0][0]).toContain("Update failed");
    expect(await screen.findByRole("button", { name: /Install 1\.5\.0/ })).toBeEnabled();
  });

  it("blocks a restart while an install is running", async () => {
    // handle_reboot() only guards against a firing and a relay test, not an
    // OTA, so restarting from this page would discard the download in flight.
    apiMock.checkOta.mockResolvedValue({
      updateAvailable: true,
      current: "1.4.0",
      latest: "1.5.0",
    });
    apiMock.installOta.mockResolvedValue({ ok: true, version: "1.5.0", message: "started" });
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: /Check for Updates/ }));
    await user.click(await screen.findByRole("button", { name: /Install 1\.5\.0/ }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Restart" })).toBeDisabled());
  });
});

/**
 * The recovery half of the OTA story (#177). Everything here is about not
 * stranding a user on a bad image: the firmware keeps the previous one in the
 * other slot, and until this card existed the only way back was a USB cable.
 */
describe("Settings: firmware partitions and rollback", () => {
  it("shows which image is running and which one boots next", async () => {
    await renderSettled();

    expect(await screen.findByText("Firmware Partitions")).toBeInTheDocument();
    // Both slot rows read "ota_0" until a rollback is pending, which is the
    // whole point of showing them side by side.
    expect(screen.getAllByText("ota_0")).toHaveLength(2);
    const versionRow = screen.getByText("Running Version").closest("div")!;
    expect(within(versionRow).getByText("1.4.0")).toBeInTheDocument();
    expect(screen.getByText("valid")).toBeInTheDocument();
  });

  it("asks before rolling back", async () => {
    // A rollback reboots the kiln onto different firmware. One stray click is
    // not consent for that.
    const user = userEvent.setup();
    await renderSettled();

    await user.click(await screen.findByRole("button", { name: "Roll Back" }));
    expect(apiMock.rollbackOta).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(apiMock.rollbackOta).not.toHaveBeenCalled();
  });

  it("rolls back once confirmed", async () => {
    apiMock.rollbackOta.mockResolvedValue({ acknowledged: true });
    const user = userEvent.setup();
    await renderSettled();

    await user.click(await screen.findByRole("button", { name: "Roll Back" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Roll Back" }));

    await waitFor(() => expect(apiMock.rollbackOta).toHaveBeenCalled());
    expect(toastFns.success).toHaveBeenCalledWith(expect.stringContaining("Rolling back"));
  });

  it("does not claim success for a rollback the controller never acknowledged", async () => {
    // The reboot eats the reply in the normal case — but a kiln that had
    // already dropped off the network produces the identical failure, and the
    // browser cannot tell them apart. Reporting a flat success there would be
    // a guess dressed as a fact.
    apiMock.rollbackOta.mockResolvedValue({ acknowledged: false });
    const user = userEvent.setup();
    await renderSettled();

    await user.click(await screen.findByRole("button", { name: "Roll Back" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Roll Back" }));

    await waitFor(() => expect(toastFns.warning).toHaveBeenCalled());
    expect(toastFns.success).not.toHaveBeenCalled();
    expect(toastFns.warning.mock.calls[0][0]).toContain("stopped answering");
  });

  it("reports a refused rollback", async () => {
    // 409 while a firing runs, 400 when there is no image to go back to.
    apiMock.rollbackOta.mockRejectedValue(new Error("API error 400: Rollback not available"));
    const user = userEvent.setup();
    await renderSettled();

    await user.click(await screen.findByRole("button", { name: "Roll Back" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Roll Back" }));

    await waitFor(() => expect(toastFns.error).toHaveBeenCalled());
    expect(toastFns.error.mock.calls[0][0]).toContain("Rollback refused");
  });

  it("makes no claim about rollback while the status is still loading", async () => {
    // "No previous firmware to roll back to" is a statement about the device.
    // Rendering it from an unresolved query asserts something nothing has said
    // yet — and it used to print directly under "could not read the state".
    let release: (value: unknown) => void = () => {};
    apiMock.otaStatus.mockImplementation(() => new Promise((r) => (release = r)));
    await renderSettled();

    expect(await screen.findByText(/Reading the partition state/)).toBeInTheDocument();
    expect(screen.queryByText(/No previous firmware to roll back to/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Roll Back" })).not.toBeInTheDocument();

    release(otaStatus());
    expect(await screen.findByRole("button", { name: "Roll Back" })).toBeInTheDocument();
  });

  it("offers a retry when the status could not be read, and no rollback verdict", async () => {
    apiMock.otaStatus.mockRejectedValueOnce(new Error("API error 404: Not found"));
    const user = userEvent.setup();
    await renderSettled();

    expect(await screen.findByText(/Could not read the partition state/)).toBeInTheDocument();
    expect(screen.queryByText(/No previous firmware to roll back to/)).not.toBeInTheDocument();

    // The card is otherwise a dead end: nothing else on the page refetches it,
    // so a kiln that has finished rebooting stays "unreadable" until reload.
    apiMock.otaStatus.mockResolvedValue(otaStatus());
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("button", { name: "Roll Back" })).toBeInTheDocument();
  });

  it("drops the stale partition state when an update finishes installing", async () => {
    // The slot, version and image state on screen belong to the firmware that
    // was just replaced, and the new image may be sitting in pending-verify
    // with a Confirm button nobody is being shown. A controller reboot does not
    // take the browser offline, so nothing else invalidates this.
    apiMock.checkOta.mockResolvedValue({
      updateAvailable: true,
      current: "1.4.0",
      latest: "1.5.0",
    });
    apiMock.installOta.mockResolvedValue({ ok: true, version: "1.5.0", message: "started" });
    const user = userEvent.setup();
    await renderSettled();
    expect(await screen.findByRole("button", { name: "Roll Back" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Check for Updates/ }));
    await user.click(await screen.findByRole("button", { name: /Install 1\.5\.0/ }));
    await waitFor(() => expect(wsSubscribers.length).toBeGreaterThan(0));

    // The refetch it triggers hits a rebooting kiln, which is the honest state.
    apiMock.otaStatus.mockRejectedValue(new Error("API error 503: rebooting"));
    pushFrame({ type: "ota_complete", data: { percent: 100 } });

    expect(await screen.findByText(/Could not read the partition state/)).toBeInTheDocument();
  });

  it("offers no rollback when the device says there is nothing behind it", async () => {
    // Pressing it would take a 400; saying why beats a dead button.
    apiMock.otaStatus.mockResolvedValue(otaStatus({ rollbackAvailable: false }));
    await renderSettled();

    await waitFor(() => expect(screen.getByRole("button", { name: "Roll Back" })).toBeDisabled());
    expect(screen.getByText(/No previous firmware to roll back to/)).toBeInTheDocument();
  });

  it("does not offer a rollback mid-firing", async () => {
    // handle_ota_rollback() answers 409, and rebooting would abandon the load.
    useKilnStore.setState({
      firingProgress: { ...useKilnStore.getState().firingProgress, isActive: true },
    });
    await renderSettled();

    await waitFor(() => expect(screen.getByRole("button", { name: "Roll Back" })).toBeDisabled());
  });

  it("offers to confirm an image that is still pending verification", async () => {
    apiMock.otaStatus.mockResolvedValue(otaStatus({ pendingVerify: true }));
    apiMock.confirmOta.mockResolvedValue({ ok: true, message: "Firmware confirmed as valid" });
    const user = userEvent.setup();
    await renderSettled();

    expect(await screen.findByText("Pending verification")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(apiMock.confirmOta).toHaveBeenCalled());
    // The firmware's own wording — it distinguishes a confirmation from a
    // no-op on an already-valid image, and the user should see which happened.
    expect(toastFns.success).toHaveBeenCalledWith("Firmware confirmed as valid");
  });

  it("hides the confirm control once the image is valid", async () => {
    await renderSettled();

    await waitFor(() => expect(apiMock.otaStatus).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  });

  it("says so when the partition state cannot be read", async () => {
    // A controller too old to serve /ota/status 404s it. Rendering an empty
    // card would read as "no previous firmware", which is a different claim.
    apiMock.otaStatus.mockRejectedValue(new Error("API error 404: Not found"));
    await renderSettled();

    expect(await screen.findByText(/Could not read the partition state/)).toBeInTheDocument();
  });
});

describe("Settings: manual firmware upload", () => {
  async function chooseFile(user: ReturnType<typeof userEvent.setup>) {
    const file = new File([new Uint8Array([1, 2, 3])], "bisque.bin", {
      type: "application/octet-stream",
    });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, file);
    return file;
  }

  it("cannot be started without a file", async () => {
    await renderSettled();
    expect(screen.getByRole("button", { name: /Upload Firmware/ })).toBeDisabled();
  });

  it("uploads the chosen binary and reports the reboot", async () => {
    apiMock.uploadOta.mockResolvedValue({ ok: true });
    const user = userEvent.setup();
    await renderSettled();
    const file = await chooseFile(user);

    await user.click(screen.getByRole("button", { name: /Upload Firmware/ }));

    await waitFor(() => expect(apiMock.uploadOta).toHaveBeenCalled());
    expect(apiMock.uploadOta.mock.calls[0][0]).toBe(file);
    await waitFor(() =>
      expect(toastFns.success).toHaveBeenCalledWith("Firmware uploaded — controller is rebooting"),
    );
  });

  it("shows upload progress as it is reported", async () => {
    // Progress comes from the XHR upload callback, not the frame stream.
    let report!: (pct: number) => void;
    apiMock.uploadOta.mockImplementation(
      (_file: File, onProgress?: (pct: number) => void) =>
        new Promise(() => {
          report = onProgress!;
        }),
    );
    const user = userEvent.setup();
    await renderSettled();
    await chooseFile(user);

    await user.click(screen.getByRole("button", { name: /Upload Firmware/ }));
    await waitFor(() => expect(report).toBeDefined());

    report(55);
    expect(await screen.findByText("55%")).toBeInTheDocument();
  });

  it("clears the progress bar when the upload fails", async () => {
    // Leaving it at "Uploading firmware..." is the #135 hang all over again,
    // this time in the component rather than the service.
    apiMock.uploadOta.mockRejectedValue(new Error("OTA error 400: Invalid image header"));
    const user = userEvent.setup();
    await renderSettled();
    await chooseFile(user);

    await user.click(screen.getByRole("button", { name: /Upload Firmware/ }));

    await waitFor(() => expect(toastFns.error).toHaveBeenCalled());
    expect(toastFns.error.mock.calls[0][0]).toContain("OTA failed");
    expect(screen.queryByText("Uploading firmware...")).not.toBeInTheDocument();
    // And the same file can be retried.
    expect(screen.getByRole("button", { name: /Upload Firmware/ })).toBeEnabled();
  });

  it("forgets the file after a successful upload", async () => {
    // The controller is rebooting into the new image; offering to send the same
    // binary again is an invitation to flash a device mid-restart.
    apiMock.uploadOta.mockResolvedValue({ ok: true });
    const user = userEvent.setup();
    await renderSettled();
    await chooseFile(user);
    expect(screen.getByText(/bisque\.bin/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Upload Firmware/ }));

    await waitFor(() => expect(screen.queryByText(/bisque\.bin/)).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Upload Firmware/ })).toBeDisabled();
  });
});

describe("Settings: Wi-Fi", () => {
  it("clears the stored credentials on Forget Network", async () => {
    apiMock.clearWifi.mockResolvedValue({ ok: true, message: "Wi-Fi credentials cleared" });
    const user = userEvent.setup();
    await renderSettled();

    await user.click(await screen.findByRole("button", { name: "Forget Network" }));

    await waitFor(() => expect(apiMock.clearWifi).toHaveBeenCalled());
    expect(toastFns.success).toHaveBeenCalledWith("Wi-Fi credentials cleared");
  });

  it("empties the SSID field so it does not look like the network is still saved", async () => {
    apiMock.clearWifi.mockResolvedValue({ ok: true, message: "Cleared" });
    const user = userEvent.setup();
    await renderSettled();

    const ssid = await screen.findByLabelText("Network Name (SSID)");
    await waitFor(() => expect(ssid).toHaveValue("Studio"));

    await user.click(screen.getByRole("button", { name: "Forget Network" }));
    await waitFor(() => expect(ssid).toHaveValue(""));
  });

  it("reports a failed clear instead of pretending it worked", async () => {
    apiMock.clearWifi.mockRejectedValue(new Error("API error 500"));
    const user = userEvent.setup();
    await renderSettled();

    await user.click(await screen.findByRole("button", { name: "Forget Network" }));

    await waitFor(() =>
      expect(toastFns.error).toHaveBeenCalledWith("Failed to clear Wi-Fi credentials"),
    );
  });

  it("offers Forget only when there is something saved", async () => {
    apiMock.getWifi.mockResolvedValue({ ...wifiInfo, hasSavedCredentials: false, savedSsid: "" });
    await renderSettled();
    await screen.findByText("Wi-Fi Network");
    expect(screen.queryByRole("button", { name: "Forget Network" })).not.toBeInTheDocument();
  });

  it("saves credentials and restarts to join the new network", async () => {
    apiMock.saveWifi.mockResolvedValue({ ok: true, message: "Saved" });
    apiMock.reboot.mockResolvedValue({ ok: true, message: "Restarting" });
    const user = userEvent.setup();
    await renderSettled();

    const ssid = await screen.findByLabelText("Network Name (SSID)");
    await user.clear(ssid);
    await user.type(ssid, "Kiln Shed");
    await user.type(screen.getByLabelText("Password"), "hunter2hunter2");
    await user.click(screen.getByRole("button", { name: /Save & Restart/ }));

    await waitFor(() =>
      expect(apiMock.saveWifi).toHaveBeenCalledWith("Kiln Shed", "hunter2hunter2"),
    );
    // The reboot is what makes the credentials take effect; without it the
    // controller stays on the old network and the save looks like a no-op.
    await waitFor(() => expect(apiMock.reboot).toHaveBeenCalled());
  });

  it("does not reboot when the credentials were refused", async () => {
    apiMock.saveWifi.mockRejectedValue(new Error("API error 400: Missing ssid"));
    const user = userEvent.setup();
    await renderSettled();

    const ssid = await screen.findByLabelText("Network Name (SSID)");
    await user.clear(ssid);
    await user.type(ssid, "Kiln Shed");
    await user.click(screen.getByRole("button", { name: /Save & Restart/ }));

    await waitFor(() =>
      expect(toastFns.error).toHaveBeenCalledWith("Failed to save Wi-Fi credentials"),
    );
    expect(apiMock.reboot).not.toHaveBeenCalled();
  });

  it("warns rather than claiming success when the restart is refused", async () => {
    // The credentials *are* saved; they just will not apply until a power
    // cycle. Reporting a plain failure would send the user to re-enter them.
    apiMock.saveWifi.mockResolvedValue({ ok: true, message: "Saved" });
    apiMock.reboot.mockRejectedValue(new Error("API error 409: Firing in progress"));
    const user = userEvent.setup();
    await renderSettled();

    const ssid = await screen.findByLabelText("Network Name (SSID)");
    await user.clear(ssid);
    await user.type(ssid, "Kiln Shed");
    await user.click(screen.getByRole("button", { name: /Save & Restart/ }));

    await waitFor(() => expect(toastFns.warning).toHaveBeenCalled());
    expect(toastFns.warning.mock.calls[0][0]).toContain("Power-cycle");
  });
});

describe("Settings: thermocouple diagnostics", () => {
  it("shows the reading the device returns", async () => {
    apiMock.getThermocoupleDiag.mockResolvedValue({
      temperatureC: 24.5,
      internalTempC: 22,
      fault: false,
      openCircuit: false,
      shortGnd: false,
      shortVcc: false,
    });
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: /Read Thermocouple/ }));
    expect(await screen.findByText("No faults detected")).toBeInTheDocument();
  });

  it("reports a failed read rather than showing a stale panel", async () => {
    apiMock.getThermocoupleDiag.mockRejectedValue(new Error("API error 500"));
    const user = userEvent.setup();
    await renderSettled();

    await user.click(screen.getByRole("button", { name: /Read Thermocouple/ }));
    await waitFor(() => expect(toastFns.error).toHaveBeenCalledWith("Failed to read thermocouple"));
  });
});
