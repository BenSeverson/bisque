import { create } from "zustand";
import { FiringProgress, TemperatureDataPoint, coerceFiringStatus } from "../types/kiln";
import { kilnWS, WSMessage, WSConnectionState } from "../services/websocket";

interface KilnState {
  // UI state
  selectedProfileId: string | null;
  setSelectedProfileId: (id: string | null) => void;

  // Connection health. Without this the dashboard cannot distinguish a live
  // reading from the last one received before the device dropped off.
  connectionState: WSConnectionState;
  lastUpdateAt: number | null;

  // Real-time firing data (from WebSocket)
  firingProgress: FiringProgress;
  currentTempData: TemperatureDataPoint[];
  resetTempData: () => void;

  // WebSocket lifecycle
  initWebSocket: () => () => void;
}

const initialProgress: FiringProgress = {
  isActive: false,
  profileId: null,
  startTime: null,
  currentTemp: 20,
  targetTemp: 20,
  currentSegment: 0,
  totalSegments: 0,
  elapsedTime: 0,
  estimatedTimeRemaining: 0,
  status: "idle",
};

const initialTempData: TemperatureDataPoint[] = [{ time: 0, temp: 20, target: 20 }];

const MAX_TEMP_POINTS = 600;

export const useKilnStore = create<KilnState>((set) => ({
  selectedProfileId: null,
  setSelectedProfileId: (id) => set({ selectedProfileId: id }),

  connectionState: "offline",
  lastUpdateAt: null,

  firingProgress: initialProgress,
  currentTempData: [...initialTempData],
  resetTempData: () => set({ currentTempData: [...initialTempData] }),

  initWebSocket: () => {
    kilnWS.connect();

    const unsubscribeStatus = kilnWS.subscribeStatus((state: WSConnectionState) => {
      set({ connectionState: state });
    });

    const unsubscribe = kilnWS.subscribe((msg: WSMessage) => {
      if (msg.type === "temp_update") {
        const d = msg.data;
        const receivedAt = Date.now();
        set((state) => {
          const prev = state.firingProgress;

          /* A firing can start or stop from anywhere — the LCD, the iOS app,
             another browser tab — and this client only ever reset its chart
             from its own Start/Stop handlers. Detect the discontinuity from the
             stream itself, or a new firing's low-time points get appended after
             the previous series' high-time tail and the chart's axis runs
             backward. */
          // Only from the second frame onward: on the very first frame every
          // field looks like a transition away from the initial state, which
          // would discard the point seeded by the mount-time getStatus().
          const seenAFrame = state.lastUpdateAt !== null;
          const isNewFiring =
            seenAFrame &&
            ((!!d.profileId && d.profileId !== prev.profileId) ||
              d.elapsedTime < prev.elapsedTime ||
              (d.isActive && !prev.isActive));

          /* Once a firing ends, its elapsed/segment/ETA figures describe
             nothing. Leaving them meant the dashboard showed a dead firing's
             numbers beside status "Idle". */
          const endedFiring = !d.isActive && prev.isActive;
          const timeMin = Math.round(d.elapsedTime / 60);
          const newPoint = {
            time: timeMin,
            temp: Math.round(d.currentTemp),
            target: Math.round(d.targetTemp),
          };
          // Dedupe by minute: replace last entry if its time matches; otherwise append.
          // Without this, sub-minute WS updates would flood the buffer (e.g. 1Hz → 60
          // points/min) and the 200-cap would only retain ~3 minutes of history.
          const series = isNewFiring ? [] : state.currentTempData;
          const last = series[series.length - 1];
          let newData: TemperatureDataPoint[];
          if (isNewFiring) {
            newData = [newPoint];
          } else if (last && last.time === timeMin) {
            newData = series.slice(0, -1);
            newData.push(newPoint);
          } else {
            newData = [...series, newPoint];
            if (newData.length > MAX_TEMP_POINTS) newData.shift();
          }

          /* Follow the running firing's profile. The dashboard resolves segment
             names and the profile overlay through selectedProfileId, so adopting
             only firingProgress.profileId would still leave a firing started
             from the LCD or the iOS app without segment names. Only while
             active, so it never hijacks a selection the user is browsing. */
          const followProfile = d.isActive && !!d.profileId && d.profileId !== prev.profileId;

          return {
            lastUpdateAt: receivedAt,
            ...(followProfile ? { selectedProfileId: d.profileId } : {}),
            firingProgress: {
              isActive: d.isActive,
              profileId: d.profileId ?? prev.profileId,
              startTime: prev.startTime,
              currentTemp: d.currentTemp,
              targetTemp: d.targetTemp,
              currentSegment: endedFiring ? 0 : d.currentSegment,
              totalSegments: endedFiring ? 0 : d.totalSegments,
              elapsedTime: endedFiring ? 0 : d.elapsedTime,
              estimatedTimeRemaining: endedFiring ? 0 : d.estimatedTimeRemaining,
              status: coerceFiringStatus(d.status),
            },
            currentTempData: newData,
          };
        });
      }
    });

    return () => {
      unsubscribeStatus();
      unsubscribe();
      kilnWS.disconnect();
    };
  },
}));
