import { FiringProfile } from '../types/kiln';

export const mockProfiles: FiringProfile[] = [
  {
    id: 'bisque-04',
    name: 'Bisque Cone 04',
    description: 'Standard bisque firing to cone 04 (1060°C)',
    maxTemp: 1060,
    estimatedDuration: 540, // 9 hours
    segments: [
      {
        id: 'seg-1',
        name: 'Warm-up',
        rampRate: 100,
        targetTemp: 200,
        holdTime: 60,
      },
      {
        id: 'seg-2',
        name: 'Water smoke',
        rampRate: 50,
        targetTemp: 600,
        holdTime: 30,
      },
      {
        id: 'seg-3',
        name: 'Ramp to top',
        rampRate: 150,
        targetTemp: 1060,
        holdTime: 15,
      },
    ],
  },
  {
    id: 'glaze-6',
    name: 'Glaze Cone 6',
    description: 'Standard glaze firing to cone 6 (1222°C)',
    maxTemp: 1222,
    estimatedDuration: 480, // 8 hours
    segments: [
      {
        id: 'seg-1',
        name: 'Initial heat',
        rampRate: 150,
        targetTemp: 600,
        holdTime: 0,
      },
      {
        id: 'seg-2',
        name: 'Medium ramp',
        rampRate: 100,
        targetTemp: 1000,
        holdTime: 0,
      },
      {
        id: 'seg-3',
        name: 'Final ramp',
        rampRate: 80,
        targetTemp: 1222,
        holdTime: 10,
      },
    ],
  },
  {
    id: 'glaze-10',
    name: 'Glaze Cone 10',
    description: 'High-fire glaze to cone 10 (1305°C)',
    maxTemp: 1305,
    estimatedDuration: 600, // 10 hours
    segments: [
      {
        id: 'seg-1',
        name: 'Low heat',
        rampRate: 120,
        targetTemp: 500,
        holdTime: 0,
      },
      {
        id: 'seg-2',
        name: 'Medium heat',
        rampRate: 150,
        targetTemp: 1000,
        holdTime: 15,
      },
      {
        id: 'seg-3',
        name: 'High heat',
        rampRate: 100,
        targetTemp: 1305,
        holdTime: 20,
      },
    ],
  },
  {
    id: 'low-fire',
    name: 'Low Fire Cone 06',
    description: 'Low temperature firing to cone 06 (999°C)',
    maxTemp: 999,
    estimatedDuration: 420, // 7 hours
    segments: [
      {
        id: 'seg-1',
        name: 'Warm-up',
        rampRate: 100,
        targetTemp: 400,
        holdTime: 30,
      },
      {
        id: 'seg-2',
        name: 'Ramp to top',
        rampRate: 120,
        targetTemp: 999,
        holdTime: 10,
      },
    ],
  },
  {
    id: 'crystalline',
    name: 'Crystalline Glaze',
    description: 'Special crystalline glaze cycle with hold and cool',
    maxTemp: 1260,
    estimatedDuration: 720, // 12 hours
    segments: [
      {
        id: 'seg-1',
        name: 'Initial ramp',
        rampRate: 200,
        targetTemp: 1260,
        holdTime: 30,
      },
      {
        id: 'seg-2',
        name: 'Crystal growth',
        rampRate: -200,
        targetTemp: 1100,
        holdTime: 120,
      },
      {
        id: 'seg-3',
        name: 'Cool down',
        rampRate: -150,
        targetTemp: 800,
        holdTime: 0,
      },
    ],
  },
];
