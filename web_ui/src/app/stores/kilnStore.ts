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
          const timeMin = Math.round(d.elapsedTime / 60);
          const newPoint = {
            time: timeMin,
            temp: Math.round(d.currentTemp),
            target: Math.round(d.targetTemp),
          };
          // Dedupe by minute: replace last entry if its time matches; otherwise append.
          // Without this, sub-minute WS updates would flood the buffer (e.g. 1Hz → 60
          // points/min) and the 200-cap would only retain ~3 minutes of history.
          const last = state.currentTempData[state.currentTempData.length - 1];
          let newData: TemperatureDataPoint[];
          if (last && last.time === timeMin) {
            newData = state.currentTempData.slice(0, -1);
            newData.push(newPoint);
          } else {
            newData = [...state.currentTempData, newPoint];
            if (newData.length > MAX_TEMP_POINTS) newData.shift();
          }

          return {
            lastUpdateAt: receivedAt,
            firingProgress: {
              isActive: d.isActive,
              profileId: state.firingProgress.profileId,
              startTime: state.firingProgress.startTime,
              currentTemp: d.currentTemp,
              targetTemp: d.targetTemp,
              currentSegment: d.currentSegment,
              totalSegments: d.totalSegments,
              elapsedTime: d.elapsedTime,
              estimatedTimeRemaining: d.estimatedTimeRemaining,
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
