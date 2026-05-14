/**
 * Zod schemas for every REST-API response the frontend consumes. This is the
 * canonical contract between the firmware (which produces the JSON in
 * components/web_server/api_json.c) and the frontend (which parses it).
 *
 * Two test suites validate against these schemas:
 *
 * 1. mock-server/handlers.test.ts spins up the TS mock-server in-process and
 *    asserts every endpoint matches — catches drift in the mock-server itself.
 * 2. test/contracts/firmwareContract.test.ts loads JSON fixtures emitted by
 *    the C test_api_json binary and asserts the firmware output matches —
 *    catches drift between firmware and frontend (Layer 3).
 *
 * Any time the frontend's expectations change, update these schemas plus the
 * matching C builder in api_json.c in the same PR.
 */
import { z } from "zod";

export const firingProgressResponseSchema = z.object({
  isActive: z.boolean(),
  profileId: z.string(),
  currentTemp: z.number(),
  targetTemp: z.number(),
  currentSegment: z.number(),
  totalSegments: z.number(),
  elapsedTime: z.number(),
  estimatedTimeRemaining: z.number(),
  status: z.string(),
  thermocouple: z.object({
    temperature: z.number(),
    internalTemp: z.number(),
    fault: z.boolean(),
    openCircuit: z.boolean(),
    shortGnd: z.boolean(),
    shortVcc: z.boolean(),
  }),
});

export const coneEntrySchema = z.object({
  id: z.number(),
  name: z.string(),
  slowTempC: z.number(),
  mediumTempC: z.number(),
  fastTempC: z.number(),
});

export const historyRecordSchema = z.object({
  id: z.number(),
  startTime: z.number(),
  profileName: z.string(),
  profileId: z.string(),
  peakTemp: z.number(),
  durationS: z.number(),
  outcome: z.enum(["complete", "error", "aborted"]),
  errorCode: z.number(),
});

export const systemInfoSchema = z.object({
  firmware: z.string(),
  model: z.string(),
  uptimeSeconds: z.number(),
  freeHeap: z.number(),
  emergencyStop: z.boolean(),
  lastErrorCode: z.number(),
  elementHoursS: z.number(),
  spiffsTotal: z.number(),
  spiffsUsed: z.number(),
  boardTempC: z.number(),
});

export const autotuneStatusSchema = z.object({
  state: z.enum(["idle", "running", "stopped", "complete"]),
  elapsedTime: z.number(),
  targetTemp: z.number(),
  currentTemp: z.number(),
  currentGains: z.object({
    kp: z.number(),
    ki: z.number(),
    kd: z.number(),
  }),
});

export const thermocoupleDiagSchema = z.object({
  temperatureC: z.number(),
  internalTempC: z.number(),
  fault: z.boolean(),
  openCircuit: z.boolean(),
  shortGnd: z.boolean(),
  shortVcc: z.boolean(),
  readingAgeMs: z.number(),
  tcOffsetC: z.number(),
  temperatureAdjustedC: z.number(),
});
