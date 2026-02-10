export interface FiringSegment {
  id: string;
  name: string;
  rampRate: number; // degrees per hour
  targetTemp: number; // degrees
  holdTime: number; // minutes
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
  elapsedTime: number; // minutes
  estimatedTimeRemaining: number; // minutes
}

export interface KilnSettings {
  tempUnit: 'C' | 'F';
  maxSafeTemp: number;
  alarmEnabled: boolean;
  autoShutdown: boolean;
  notificationsEnabled: boolean;
}

export interface TemperatureDataPoint {
  time: number; // minutes
  temp: number;
  target: number;
}
