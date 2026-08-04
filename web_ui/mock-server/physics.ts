export const AMBIENT = 20;

function gaussianNoise(stddev: number): number {
  const u1 = Math.random();
  const u2 = Math.random();
  return stddev * Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

/**
 * First-order lag model for kiln temperature.
 * Heating is faster (active element), cooling is slower (passive radiation).
 */
export function updateTemperature(currentTemp: number, setpoint: number, dt: number): number {
  const isHeating = setpoint > currentTemp;
  const tauHeat = 120; // seconds — active heating response
  const tauCool = 300; // seconds — passive cooling response
  const tau = isHeating ? tauHeat : tauCool;

  const approach = 1 - Math.exp(-dt / tau);
  let newTemp = currentTemp + (setpoint - currentTemp) * approach;

  // Small overshoot (1-3%) when approaching hold from a fast ramp
  if (isHeating) {
    const distance = Math.abs(setpoint - currentTemp);
    if (distance < 15 && distance > 2) {
      const overshootFactor = 0.015 * (1 - distance / 15);
      newTemp += setpoint * overshootFactor * Math.random();
    }
  }

  // Thermocouple jitter ~±1°C
  newTemp += gaussianNoise(0.5);

  return Math.max(AMBIENT, newTemp);
}

/** Tracking error (°C) that alone would call for full power. */
const DUTY_PROP_BAND_C = 40;
/** Duty a kiln needs just to hold DUTY_MAX_TEMP against its losses. */
const DUTY_HOLD_AT_MAX = 0.55;
const DUTY_MAX_TEMP = 1300;

/**
 * Element duty (0–1) a controller would be commanding here, so the demo's
 * "Element Power" reading behaves like a real kiln's (#180).
 *
 * The lag model above has no element in it — temperature just relaxes toward
 * the setpoint — so the duty has to be reconstructed. Two terms, matching what
 * a PID settles into: a proportional response to the tracking error, plus the
 * standing power a hot kiln needs merely to hold position against its losses.
 * In practice the losses term dominates, so the reading climbs with the kiln
 * (a few percent while warming, ~45% up at cone 04) and spikes only when the
 * setpoint pulls away faster than the kiln follows.
 */
export function elementDuty(currentTemp: number, setpoint: number): number {
  const losses = DUTY_HOLD_AT_MAX * ((setpoint - AMBIENT) / (DUTY_MAX_TEMP - AMBIENT));
  const proportional = (setpoint - currentTemp) / DUTY_PROP_BAND_C;
  return Math.min(1, Math.max(0, losses + proportional));
}

/** Passive cooling toward ambient after stop. */
export function coolingTemperature(currentTemp: number, dt: number): number {
  const tau = 600; // slow passive cooling
  const approach = 1 - Math.exp(-dt / tau);
  let newTemp = currentTemp + (AMBIENT - currentTemp) * approach;
  newTemp += gaussianNoise(0.5);
  return Math.max(AMBIENT, newTemp);
}
