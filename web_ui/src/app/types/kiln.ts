export interface FiringSegment {
  id: string;
  name: string;
  rampRate: number; // degrees per hour
  targetTemp: number; // degrees
  holdTime: number; // minutes (0 = hold indefinitely)
}

export interface FiringProfile {
  id: string;
  name: string;
  description: string;
  segments: FiringSegment[];
  maxTemp: number;
  estimatedDuration: number; // minutes
}

export interface FiringProgress {
  isActive: boolean;
  profileId: string | null;
  startTime: number | null;
  currentTemp: number;
  targetTemp: number;
  currentSegment: number;
  totalSegments: number;
  elapsedTime: number; // seconds
  estimatedTimeRemaining: number; // seconds
  status: string;
}

export interface KilnSettings {
  tempUnit: 'C' | 'F';
  maxSafeTemp: number;
  alarmEnabled: boolean;
  autoShutdown: boolean;
  notificationsEnabled: boolean;
  tcOffsetC: number;
  webhookUrl: string;
  apiToken?: string;          // write-only: only sent when changing the token
  apiTokenSet?: boolean;      // read: whether a token is currently set
  elementWatts: number;
  electricityCostKwh: number;
}

export interface TemperatureDataPoint {
  time: number; // minutes
  temp: number;
  target: number;
}

export interface ConeEntry {
  id: number;
  name: string;
  slowTempC: number;
  mediumTempC: number;
  fastTempC: number;
}

export interface HistoryRecord {
  id: number;
  startTime: number; // Unix timestamp
  profileName: string;
  profileId: string;
  peakTemp: number;
  durationS: number;
  outcome: 'complete' | 'error' | 'aborted';
  errorCode: number;
}
