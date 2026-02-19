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
export function updateTemperature(
  currentTemp: number,
  setpoint: number,
  dt: number,
): number {
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

/** Passive cooling toward ambient after stop. */
export function coolingTemperature(currentTemp: number, dt: number): number {
  const tau = 600; // slow passive cooling
  const approach = 1 - Math.exp(-dt / tau);
  let newTemp = currentTemp + (AMBIENT - currentTemp) * approach;
  newTemp += gaussianNoise(0.5);
  return Math.max(AMBIENT, newTemp);
}
