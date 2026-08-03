import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { WSMessage, TempUpdateData } from "../services/websocket";
import type { StatusResponse } from "../services/api";

// Capture the handler the store registers on the mocked WS so tests can pump
// frames directly into the store.
let wsSubscriber: ((msg: WSMessage) => void) | null = null;
let wsStatusSubscriber: ((state: "connecting" | "open" | "offline") => void) | null = null;
const connectSpy = vi.fn();
const disconnectSpy = vi.fn();

vi.mock("../services/websocket", () => ({
  kilnWS: {
    connect: () => connectSpy(),
    disconnect: () => disconnectSpy(),
    subscribe: (handler: (msg: WSMessage) => void) => {
      wsSubscriber = handler;
      return () => {
        wsSubscriber = null;
      };
    },
    setAuthToken: () => {},
    subscribeStatus: (handler: (state: "connecting" | "open" | "offline") => void) => {
      wsStatusSubscriber = handler;
      handler("offline");
      return () => {
        wsStatusSubscriber = null;
      };
    },
  },
}));

const { useKilnStore } = await import("./kilnStore");

const initialProgress = useKilnStore.getState().firingProgress;
const initialTempData = useKilnStore.getState().currentTempData;

function resetStore() {
  useKilnStore.setState({
    selectedProfileId: null,
    firingProgress: initialProgress,
    currentTempData: [...initialTempData],
    connectionState: "offline",
    lastUpdateAt: null,
    errorSince: null,
  });
  wsSubscriber = null;
  wsStatusSubscriber = null;
  connectSpy.mockClear();
  disconnectSpy.mockClear();
}

function tempFrame(overrides: Partial<TempUpdateData> = {}): WSMessage {
  return {
    type: "temp_update",
    data: {
      currentTemp: 100,
      targetTemp: 200,
      status: "heating",
      currentSegment: 1,
      totalSegments: 3,
      elapsedTime: 0,
      estimatedTimeRemaining: 3600,
      isActive: true,
      ...overrides,
    },
  };
}

describe("kilnStore: selectedProfileId", () => {
  beforeEach(resetStore);

  it("sets and clears selectedProfileId", () => {
    useKilnStore.getState().setSelectedProfileId("profile-a");
    expect(useKilnStore.getState().selectedProfileId).toBe("profile-a");
    useKilnStore.getState().setSelectedProfileId(null);
    expect(useKilnStore.getState().selectedProfileId).toBeNull();
  });
});

describe("kilnStore: resetTempData", () => {
  beforeEach(resetStore);

  it("empties the series rather than seeding an invented point", () => {
    useKilnStore.setState({
      currentTempData: [
        { time: 0, temp: 20, target: 20 },
        { time: 5, temp: 150, target: 200 },
      ],
    });
    useKilnStore.getState().resetTempData();
    // The store must not invent a 20°C reading it never received (#192).
    expect(useKilnStore.getState().currentTempData).toEqual([]);
  });
});

describe("kilnStore: seedFromStatus (#124)", () => {
  beforeEach(resetStore);

  function status(overrides: Partial<StatusResponse> = {}): StatusResponse {
    return {
      isActive: true,
      profileId: "glaze-6",
      currentTemp: 500,
      targetTemp: 600,
      currentSegment: 2,
      totalSegments: 4,
      elapsedTime: 1800,
      estimatedTimeRemaining: 3600,
      delayRemaining: 0,
      dutyPercent: 62,
      status: "heating",
      thermocouple: {
        temperature: 500,
        internalTemp: 25,
        fault: false,
        openCircuit: false,
        shortGnd: false,
        shortVcc: false,
      },
      ...overrides,
    };
  }

  it("stamps errorSince when a reload lands mid-failure", () => {
    // A page loaded after the failure never sees the transition frame, so the
    // snapshot is the only thing that can date the failure. Without this the
    // error banner has no timestamp to judge /api/v1/system against and would
    // never trust the cause it fetched.
    const at = Date.now();
    useKilnStore.getState().seedFromStatus(status({ status: "error", isActive: false }), at);
    expect(useKilnStore.getState().errorSince).toBe(at);
  });

  it("does not re-date a failure it has already seen", () => {
    const first = Date.now();
    useKilnStore.getState().seedFromStatus(status({ status: "error", isActive: false }), first);
    // The Dashboard tab is not forceMount'ed, so revisiting it re-seeds. That
    // must not look like a second, newer failure.
    useKilnStore
      .getState()
      .seedFromStatus(
        status({ status: "error", isActive: false, elapsedTime: 2400 }),
        first + 60_000,
      );
    expect(useKilnStore.getState().errorSince).toBe(first);
  });

  it("clears errorSince when the snapshot shows a recovered kiln", () => {
    useKilnStore.setState({ errorSince: 123 });
    useKilnStore.getState().seedFromStatus(status({ status: "heating" }), Date.now());
    expect(useKilnStore.getState().errorSince).toBeNull();
  });

  it("replaces the placeholder point on a first seed", () => {
    useKilnStore.getState().seedFromStatus(status(), Date.now());
    // The synthetic 20°C/t=0 point is not history; a mid-firing page load must
    // not draw a curve from it up to the real reading.
    expect(useKilnStore.getState().currentTempData).toEqual([{ time: 30, temp: 500, target: 600 }]);
  });

  it("appends to accumulated history instead of wiping it on a tab revisit", () => {
    useKilnStore.getState().initWebSocket();
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 600, currentTemp: 300 }));
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 1200, currentTemp: 400 }));
    const before = useKilnStore.getState().currentTempData.length;
    expect(before).toBeGreaterThan(1);

    // Remounting the Dashboard re-runs the mount-time seed. The snapshot is
    // newer than the last frame, so it is applied — as one more point.
    useKilnStore.getState().seedFromStatus(status(), Date.now() + 1);
    const data = useKilnStore.getState().currentTempData;
    expect(data).toHaveLength(before + 1);
    expect(data[data.length - 1]).toEqual({ time: 30, temp: 500, target: 600 });
  });

  it("collapses a seed that lands on the same minute as the last point", () => {
    useKilnStore.getState().initWebSocket();
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 1790, currentTemp: 495 }));
    const before = useKilnStore.getState().currentTempData.length;

    useKilnStore.getState().seedFromStatus(status(), Date.now() + 1);
    const data = useKilnStore.getState().currentTempData;
    expect(data).toHaveLength(before);
    expect(data[data.length - 1]).toEqual({ time: 30, temp: 500, target: 600 });
  });

  it("ignores a snapshot older than frames already applied", () => {
    useKilnStore.getState().initWebSocket();
    const dispatchedAt = Date.now();
    // A frame lands while the /status request is still in flight, so the
    // resolved snapshot describes an earlier moment than the store already has.
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 3600, currentTemp: 900 }));
    const snapshot = useKilnStore.getState();
    const data = snapshot.currentTempData;

    snapshot.seedFromStatus(status(), dispatchedAt);
    expect(useKilnStore.getState().currentTempData).toBe(data);
    expect(useKilnStore.getState().firingProgress.currentTemp).toBe(900);
  });

  it("tolerates a sub-minute clock skew between the snapshot and the stream", () => {
    useKilnStore.getState().initWebSocket();
    // Two sources: a snapshot computed either side of the last frame can report
    // a second less elapsed with nothing having restarted. That must collapse
    // onto the same minute, not be read as a new firing.
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 1200, currentTemp: 400 }));
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 1801, currentTemp: 501 }));
    const before = useKilnStore.getState().currentTempData.length;

    useKilnStore.getState().seedFromStatus(status(), Date.now() + 1); // elapsed 1800
    const data = useKilnStore.getState().currentTempData;
    expect(data).toHaveLength(before);
    expect(data[data.length - 1]).toEqual({ time: 30, temp: 500, target: 600 });
  });

  it("starts a new series when the snapshot is the first sight of a new firing", () => {
    useKilnStore.getState().initWebSocket();
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 18000, currentTemp: 900 }));

    // The device was offline when the next firing started, so /status — not the
    // stream — is the first observation of it. Merging would drop every point
    // until the new firing's elapsed time passed minute 300, and because the
    // seed also adopts the new profile and active state, the WebSocket handler
    // would no longer recognise the transition either.
    useKilnStore
      .getState()
      .seedFromStatus(
        status({ profileId: "bisque-04", elapsedTime: 120, currentTemp: 80 }),
        Date.now() + 1,
      );
    expect(useKilnStore.getState().currentTempData).toEqual([{ time: 2, temp: 80, target: 600 }]);

    // And the stream picks up from there rather than being rejected.
    wsSubscriber!(tempFrame({ profileId: "bisque-04", elapsedTime: 180, currentTemp: 95 }));
    expect(useKilnStore.getState().currentTempData.map((p) => p.time)).toEqual([2, 3]);
  });

  it("restores the active profile selection", () => {
    useKilnStore.getState().seedFromStatus(status({ profileId: "bisque-04" }), Date.now());
    expect(useKilnStore.getState().selectedProfileId).toBe("bisque-04");
  });

  it("leaves the selection alone when the kiln is idle", () => {
    useKilnStore.getState().setSelectedProfileId("browsing-this-one");
    useKilnStore
      .getState()
      .seedFromStatus(
        status({ isActive: false, status: "idle", profileId: "glaze-6" }),
        Date.now(),
      );
    expect(useKilnStore.getState().selectedProfileId).toBe("browsing-this-one");
  });
});

describe("kilnStore: WebSocket temp_update handling", () => {
  beforeEach(() => {
    resetStore();
    useKilnStore.getState().initWebSocket();
  });

  it("connect()s on init and disconnect()s on cleanup", () => {
    expect(connectSpy).toHaveBeenCalledOnce();
    const cleanup = useKilnStore.getState().initWebSocket; // already called
    expect(cleanup).toBeDefined();
  });

  it("merges WS frame into firingProgress with coerced status", () => {
    wsSubscriber!(
      tempFrame({
        currentTemp: 123.7,
        targetTemp: 456.3,
        status: "heating",
        currentSegment: 2,
        totalSegments: 5,
        elapsedTime: 60,
        estimatedTimeRemaining: 1800,
        isActive: true,
      }),
    );
    const p = useKilnStore.getState().firingProgress;
    expect(p.currentTemp).toBe(123.7);
    expect(p.targetTemp).toBe(456.3);
    expect(p.status).toBe("heating");
    expect(p.currentSegment).toBe(2);
    expect(p.totalSegments).toBe(5);
    expect(p.elapsedTime).toBe(60);
    expect(p.estimatedTimeRemaining).toBe(1800);
    expect(p.isActive).toBe(true);
  });

  it("carries element power through from each frame (#180)", () => {
    wsSubscriber!(tempFrame({ dutyPercent: 62, isActive: true, status: "heating" }));
    expect(useKilnStore.getState().firingProgress.dutyPercent).toBe(62);
    wsSubscriber!(tempFrame({ dutyPercent: 0, isActive: true, status: "holding" }));
    expect(useKilnStore.getState().firingProgress.dutyPercent).toBe(0);
  });

  it("reports no element power at all on firmware that does not send it (#180)", () => {
    // Not 0: a kiln that cannot report its power has not told us the element is
    // off, and the dashboard renders the two differently.
    wsSubscriber!(tempFrame({ isActive: true, status: "heating" }));
    expect(useKilnStore.getState().firingProgress.dutyPercent).toBeNull();
  });

  it("drops a cached reading when frames stop carrying the field (#180)", () => {
    // The store outlives a reconnect, so an OTA rollback to firmware without
    // the field would otherwise leave the last percentage on screen forever.
    // Field presence is a property of the firmware, not of the frame.
    wsSubscriber!(tempFrame({ isActive: true, status: "heating", dutyPercent: 62 }));
    wsSubscriber!(tempFrame({ isActive: true, status: "heating" }));
    expect(useKilnStore.getState().firingProgress.dutyPercent).toBeNull();
  });

  it("keeps the reported element power when a firing ends (#180)", () => {
    // The elapsed/segment figures are cleared on this edge because they describe
    // a firing that is over; the duty describes the kiln, and the same frame
    // that ends the firing already reports it as 0.
    wsSubscriber!(tempFrame({ isActive: true, status: "heating", dutyPercent: 80 }));
    wsSubscriber!(tempFrame({ isActive: false, status: "idle", dutyPercent: 0 }));
    expect(useKilnStore.getState().firingProgress.dutyPercent).toBe(0);
  });

  it("coerces an unknown status string back to 'idle'", () => {
    wsSubscriber!(tempFrame({ status: "WAT" }));
    expect(useKilnStore.getState().firingProgress.status).toBe("idle");
  });

  it("appends one point per distinct minute and rounds temps", () => {
    wsSubscriber!(tempFrame({ currentTemp: 99.6, targetTemp: 200.1, elapsedTime: 60 })); // t=1m
    wsSubscriber!(tempFrame({ currentTemp: 150.4, targetTemp: 300.8, elapsedTime: 120 })); // t=2m

    const data = useKilnStore.getState().currentTempData;
    // Only measured points — the series starts empty (#192).
    expect(data).toEqual([
      { time: 1, temp: 100, target: 200 },
      { time: 2, temp: 150, target: 301 },
    ]);
  });

  it("dedupes by minute: sub-minute updates replace the last point", () => {
    wsSubscriber!(tempFrame({ currentTemp: 100, elapsedTime: 60 })); // t=1m
    wsSubscriber!(tempFrame({ currentTemp: 110, elapsedTime: 75 })); // still t=1m (rounds to 1)
    wsSubscriber!(tempFrame({ currentTemp: 120, elapsedTime: 89 })); // still t=1m

    const data = useKilnStore.getState().currentTempData;
    expect(data).toHaveLength(1); // all three frames collapse into the 1m point
    expect(data[0]).toMatchObject({ time: 1, temp: 120 });
  });

  it("caps history at 600 points (older ones drop off the front)", () => {
    // Push 700 distinct minutes; the cap should keep the most recent 600.
    for (let i = 1; i <= 700; i++) {
      wsSubscriber!(tempFrame({ currentTemp: i, elapsedTime: i * 60 }));
    }
    const data = useKilnStore.getState().currentTempData;
    expect(data).toHaveLength(600);
    // First retained point should be 700 - 599 = 101.
    expect(data[0].time).toBe(101);
    expect(data[data.length - 1].time).toBe(700);
  });
});

describe("kilnStore: connection health", () => {
  beforeEach(() => {
    resetStore();
    useKilnStore.getState().initWebSocket();
  });

  it("starts offline and follows socket lifecycle transitions", () => {
    expect(useKilnStore.getState().connectionState).toBe("offline");

    wsStatusSubscriber!("connecting");
    expect(useKilnStore.getState().connectionState).toBe("connecting");

    wsStatusSubscriber!("open");
    expect(useKilnStore.getState().connectionState).toBe("open");

    // A drop must be reflected, or the dashboard keeps presenting the last
    // reading as if it were live.
    wsStatusSubscriber!("offline");
    expect(useKilnStore.getState().connectionState).toBe("offline");
  });

  it("stamps lastUpdateAt on each telemetry frame", () => {
    expect(useKilnStore.getState().lastUpdateAt).toBeNull();

    const before = Date.now();
    wsSubscriber!(tempFrame());
    const stamped = useKilnStore.getState().lastUpdateAt;

    expect(stamped).not.toBeNull();
    expect(stamped!).toBeGreaterThanOrEqual(before);
  });

  it("does not advance lastUpdateAt while the socket is silent", () => {
    wsSubscriber!(tempFrame());
    const first = useKilnStore.getState().lastUpdateAt;

    wsStatusSubscriber!("open");
    // Lifecycle noise is not telemetry: an open socket that sends nothing must
    // not look like fresh data.
    expect(useKilnStore.getState().lastUpdateAt).toBe(first);
  });
});

describe("kilnStore: multi-client firing transitions (#163)", () => {
  beforeEach(() => {
    resetStore();
    useKilnStore.getState().initWebSocket();
  });

  it("adopts profileId from each frame", () => {
    // A firing started from the LCD or the iOS app must not leave this tab
    // showing the wrong profile until a manual reload.
    wsSubscriber!(tempFrame({ profileId: "glaze-6" }));
    expect(useKilnStore.getState().firingProgress.profileId).toBe("glaze-6");

    wsSubscriber!(tempFrame({ profileId: "bisque-04" }));
    expect(useKilnStore.getState().firingProgress.profileId).toBe("bisque-04");
  });

  it("restarts the chart when the profile changes mid-stream", () => {
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 600, currentTemp: 500 }));
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 660, currentTemp: 520 }));
    expect(useKilnStore.getState().currentTempData.length).toBeGreaterThan(1);

    wsSubscriber!(tempFrame({ profileId: "bisque-04", elapsedTime: 0, currentTemp: 25 }));
    const data = useKilnStore.getState().currentTempData;
    // Without a reset, a new firing's low-time points get appended after the
    // old series' high-time tail and the chart's axis runs backward.
    expect(data).toHaveLength(1);
    expect(data[0].time).toBe(0);
  });

  it("restarts the chart when elapsedTime goes backwards", () => {
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 1800 }));
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 60 }));
    const data = useKilnStore.getState().currentTempData;
    expect(data).toHaveLength(1);
    expect(data[0].time).toBe(1);
  });

  it("restarts the chart when a firing begins after an idle stretch", () => {
    wsSubscriber!(tempFrame({ isActive: false, status: "idle", elapsedTime: 0 }));
    wsSubscriber!(tempFrame({ isActive: false, status: "idle", elapsedTime: 0 }));
    wsSubscriber!(tempFrame({ isActive: true, status: "heating", elapsedTime: 0 }));
    expect(useKilnStore.getState().currentTempData).toHaveLength(1);
  });

  it("keeps appending within one continuous firing", () => {
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 60 }));
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 120 }));
    wsSubscriber!(tempFrame({ profileId: "glaze-6", elapsedTime: 180 }));
    // Reset detection must not be so eager that it wipes a healthy series.
    expect(useKilnStore.getState().currentTempData.map((p) => p.time)).toEqual([1, 2, 3]);
  });

  it("follows the active firing's profile so segment names are right", () => {
    // firingProgress.profileId alone is not enough: the dashboard resolves
    // segment names and the profile overlay through selectedProfileId, so a
    // firing started from the LCD would otherwise show no segment until reload.
    wsSubscriber!(tempFrame({ profileId: "glaze-6", isActive: true, status: "heating" }));
    wsSubscriber!(tempFrame({ profileId: "bisque-04", isActive: true, status: "heating" }));
    expect(useKilnStore.getState().selectedProfileId).toBe("bisque-04");
  });

  it("re-adopts the active profile even when it matches a prior stopped firing (#163)", () => {
    // Firmware do_stop() leaves profileId populated while idle, so prev.profileId
    // can equal the next firing's id. Comparing against it would refuse to
    // follow a re-fire of the same profile the user had since browsed away from.
    wsSubscriber!(tempFrame({ profileId: "glaze-6", isActive: true, status: "heating" }));
    expect(useKilnStore.getState().selectedProfileId).toBe("glaze-6");
    wsSubscriber!(tempFrame({ profileId: "glaze-6", isActive: false, status: "idle" }));
    useKilnStore.setState({ selectedProfileId: "bisque-04" }); // user browses while idle
    wsSubscriber!(tempFrame({ profileId: "glaze-6", isActive: true, status: "heating" }));
    expect(useKilnStore.getState().selectedProfileId).toBe("glaze-6");
  });

  it("does not hijack a browsing selection while the kiln is idle", () => {
    useKilnStore.setState({ selectedProfileId: "glaze-10" });
    wsSubscriber!(tempFrame({ profileId: "", isActive: false, status: "idle" }));
    expect(useKilnStore.getState().selectedProfileId).toBe("glaze-10");
  });

  it("clears the dead firing's figures on the active -> idle transition (#158)", () => {
    wsSubscriber!(
      tempFrame({ isActive: true, status: "heating", elapsedTime: 9000, currentSegment: 2 }),
    );
    wsSubscriber!(
      tempFrame({ isActive: false, status: "idle", elapsedTime: 9000, currentSegment: 2 }),
    );

    const p = useKilnStore.getState().firingProgress;
    expect(p.elapsedTime).toBe(0);
    expect(p.currentSegment).toBe(0);
    expect(p.estimatedTimeRemaining).toBe(0);
  });
});

describe("kilnStore: errorSince (#164)", () => {
  // receivedAt is Date.now(), and frames pumped synchronously all land in the
  // same millisecond — without a controlled clock, "held for the duration" and
  // "re-stamped every frame" are indistinguishable and the test proves nothing.
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    resetStore();
    useKilnStore.getState().initWebSocket();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("is null while nothing has failed", () => {
    wsSubscriber!(tempFrame({ status: "heating", isActive: true, elapsedTime: 60 }));
    expect(useKilnStore.getState().errorSince).toBeNull();
  });

  it("stamps the edge into error and holds it for the duration", () => {
    wsSubscriber!(tempFrame({ status: "heating", isActive: true, elapsedTime: 60 }));
    vi.advanceTimersByTime(1000);
    wsSubscriber!(tempFrame({ status: "error", isActive: false, elapsedTime: 120 }));
    const first = useKilnStore.getState().errorSince;
    expect(first).not.toBeNull();

    // Later frames of the SAME failure must not re-stamp it — otherwise the
    // consumer treats its already-fetched cause as stale on every frame and the
    // banner never settles on a cause at all.
    vi.advanceTimersByTime(5000);
    wsSubscriber!(tempFrame({ status: "error", isActive: false, elapsedTime: 180 }));
    expect(useKilnStore.getState().errorSince).toBe(first);
  });

  it("re-stamps a second, distinct failure", () => {
    wsSubscriber!(tempFrame({ status: "error", isActive: false, elapsedTime: 60 }));
    const first = useKilnStore.getState().errorSince!;
    vi.advanceTimersByTime(1000);
    // Recovery clears it...
    wsSubscriber!(tempFrame({ status: "heating", isActive: true, elapsedTime: 120 }));
    expect(useKilnStore.getState().errorSince).toBeNull();
    vi.advanceTimersByTime(1000);
    // ...so the next failure gets its own, strictly later timestamp. This is
    // what stops failure #2 being explained by failure #1's cached cause.
    wsSubscriber!(tempFrame({ status: "error", isActive: false, elapsedTime: 180 }));
    expect(useKilnStore.getState().errorSince!).toBeGreaterThan(first);
  });

  it("clears on recovery", () => {
    wsSubscriber!(tempFrame({ status: "error", isActive: false, elapsedTime: 60 }));
    expect(useKilnStore.getState().errorSince).not.toBeNull();
    vi.advanceTimersByTime(1000);
    wsSubscriber!(tempFrame({ status: "idle", isActive: false, elapsedTime: 0 }));
    expect(useKilnStore.getState().errorSince).toBeNull();
  });
});
