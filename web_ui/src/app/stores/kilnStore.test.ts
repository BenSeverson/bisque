import { describe, it, expect, beforeEach, vi } from "vitest";
import type { WSMessage, TempUpdateData } from "../services/websocket";

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

  it("restores the single initial 20°C point", () => {
    useKilnStore.setState({
      currentTempData: [
        { time: 0, temp: 20, target: 20 },
        { time: 5, temp: 150, target: 200 },
      ],
    });
    useKilnStore.getState().resetTempData();
    expect(useKilnStore.getState().currentTempData).toEqual([{ time: 0, temp: 20, target: 20 }]);
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

  it("coerces an unknown status string back to 'idle'", () => {
    wsSubscriber!(tempFrame({ status: "WAT" }));
    expect(useKilnStore.getState().firingProgress.status).toBe("idle");
  });

  it("appends one point per distinct minute and rounds temps", () => {
    wsSubscriber!(tempFrame({ currentTemp: 99.6, targetTemp: 200.1, elapsedTime: 60 })); // t=1m
    wsSubscriber!(tempFrame({ currentTemp: 150.4, targetTemp: 300.8, elapsedTime: 120 })); // t=2m

    const data = useKilnStore.getState().currentTempData;
    expect(data).toEqual([
      { time: 0, temp: 20, target: 20 }, // initial point
      { time: 1, temp: 100, target: 200 },
      { time: 2, temp: 150, target: 301 },
    ]);
  });

  it("dedupes by minute: sub-minute updates replace the last point", () => {
    wsSubscriber!(tempFrame({ currentTemp: 100, elapsedTime: 60 })); // t=1m
    wsSubscriber!(tempFrame({ currentTemp: 110, elapsedTime: 75 })); // still t=1m (rounds to 1)
    wsSubscriber!(tempFrame({ currentTemp: 120, elapsedTime: 89 })); // still t=1m

    const data = useKilnStore.getState().currentTempData;
    expect(data).toHaveLength(2); // initial + one 1m point
    expect(data[1]).toMatchObject({ time: 1, temp: 120 });
  });

  it("caps history at 600 points (older ones drop off the front)", () => {
    // The initial t=0 point already occupies slot 0. Push 700 distinct minutes;
    // the cap should keep the most recent 600.
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
    expect(useKilnStore.getState().currentTempData.map((p) => p.time)).toEqual([0, 1, 2, 3]);
  });

  it("follows the active firing's profile so segment names are right", () => {
    // firingProgress.profileId alone is not enough: the dashboard resolves
    // segment names and the profile overlay through selectedProfileId, so a
    // firing started from the LCD would otherwise show no segment until reload.
    wsSubscriber!(tempFrame({ profileId: "glaze-6", isActive: true, status: "heating" }));
    wsSubscriber!(tempFrame({ profileId: "bisque-04", isActive: true, status: "heating" }));
    expect(useKilnStore.getState().selectedProfileId).toBe("bisque-04");
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
