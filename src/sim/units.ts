/**
 * Unit constants and small numeric helpers.
 *
 * The simulation works in a consistent internal set of units:
 *   distance   nautical miles (NM)
 *   altitude   feet (ft)
 *   speed      knots (kt)
 *   time       seconds (s)
 *   angles     degrees, 0-360, increasing clockwise from north
 */

export const FT_PER_NM = 6076.11548556;
export const NM_PER_FT = 1 / FT_PER_NM;
export const SEC_PER_HOUR = 3600;

/** Knots to nautical miles per second. */
export const KT_TO_NM_PER_SEC = 1 / SEC_PER_HOUR;

/** Feet per minute to feet per second. */
export const FPM_TO_FPS = 1 / 60;

export const DEG_TO_RAD = Math.PI / 180;
export const RAD_TO_DEG = 180 / Math.PI;

export function toRadians(deg: number): number {
  return deg * DEG_TO_RAD;
}

export function toDegrees(rad: number): number {
  return rad * RAD_TO_DEG;
}

export function clamp(value: number, min: number, max: number): number {
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

/** Linear interpolation, `t` clamped to [0, 1]. */
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * clamp(t, 0, 1);
}

/**
 * Move `current` towards `target` by at most `maxStep`.
 * Used everywhere a rate limit applies (bank, speed, vertical speed).
 */
export function approach(current: number, target: number, maxStep: number): number {
  const delta = target - current;
  if (Math.abs(delta) <= maxStep) return target;
  return current + Math.sign(delta) * maxStep;
}

/**
 * Indicated airspeed to true airspeed.
 *
 * The classic rule of thumb — TAS rises about 2% per 1000 ft of pressure
 * altitude — is accurate to a couple of knots up to the top of this sector
 * (FL150), which is well inside the fidelity of everything else here.
 */
export function iasToTas(iasKt: number, altitudeFt: number): number {
  return iasKt * (1 + 0.02 * (altitudeFt / 1000));
}

/** Inverse of {@link iasToTas}. */
export function tasToIas(tasKt: number, altitudeFt: number): number {
  return tasKt / (1 + 0.02 * (altitudeFt / 1000));
}

/** Format seconds-since-midnight as a UTC clock string `HH:MM:SS`. */
export function formatClock(timeSec: number): string {
  const t = ((timeSec % 86400) + 86400) % 86400;
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = Math.floor(t % 60);
  return `${pad2(h)}:${pad2(m)}:${pad2(s)}`;
}

/** Format seconds-since-midnight as a four figure UTC time `HHMM`. */
export function formatHhmm(timeSec: number): string {
  const t = ((timeSec % 86400) + 86400) % 86400;
  return `${pad2(Math.floor(t / 3600))}${pad2(Math.floor((t % 3600) / 60))}`;
}

export function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** Format an altitude the way a data block does: `080` for 8000 ft. */
export function formatFlightLevel(altitudeFt: number): string {
  const hundreds = Math.round(altitudeFt / 100);
  return hundreds < 100 ? pad2(Math.floor(hundreds / 10)) + String(hundreds % 10) : String(hundreds);
}
