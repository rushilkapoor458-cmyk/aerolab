/**
 * Geography: a local flat-earth projection plus the bearing and distance
 * arithmetic the rest of the simulation runs on.
 *
 * Everything inside the simulation happens in a local tangent plane whose
 * origin is the airport reference point. `x` is nautical miles east, `y` is
 * nautical miles north. Over a 60 NM sector an equirectangular projection is
 * accurate to a few tens of feet, far below radar resolution, and it keeps
 * every geometric routine in the simulation to plain two-dimensional algebra.
 */

import { toDegrees, toRadians } from './units.js';

export interface LatLon {
  readonly lat: number;
  readonly lon: number;
}

/** A point in the local tangent plane: NM east, NM north of the origin. */
export interface Point {
  readonly x: number;
  readonly y: number;
}

const NM_PER_DEG_LAT = 60;

export class Projection {
  private readonly lonScale: number;

  constructor(public readonly origin: LatLon) {
    this.lonScale = NM_PER_DEG_LAT * Math.cos(toRadians(origin.lat));
  }

  toLocal(ll: LatLon): Point {
    return {
      x: (ll.lon - this.origin.lon) * this.lonScale,
      y: (ll.lat - this.origin.lat) * NM_PER_DEG_LAT,
    };
  }

  toLatLon(p: Point): LatLon {
    return {
      lat: this.origin.lat + p.y / NM_PER_DEG_LAT,
      lon: this.origin.lon + p.x / this.lonScale,
    };
  }
}

/** Wrap an angle into [0, 360). */
export function normalizeDeg(deg: number): number {
  const d = deg % 360;
  return d < 0 ? d + 360 : d;
}

/**
 * Signed shortest angular difference `to - from`, in (-180, 180].
 * Positive means `to` lies clockwise (to the right) of `from`.
 */
export function angleDiff(from: number, to: number): number {
  let d = normalizeDeg(to) - normalizeDeg(from);
  if (d > 180) d -= 360;
  if (d <= -180) d += 360;
  return d;
}

/** Distance between two local points, in nautical miles. */
export function distanceNm(a: Point, b: Point): number {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

/** True bearing from `from` to `to`, degrees clockwise from north. */
export function bearingDeg(from: Point, to: Point): number {
  return normalizeDeg(toDegrees(Math.atan2(to.x - from.x, to.y - from.y)));
}

/** Advance a point `distNm` along a true track. */
export function movePoint(p: Point, trueTrackDeg: number, distNm: number): Point {
  const r = toRadians(trueTrackDeg);
  return { x: p.x + Math.sin(r) * distNm, y: p.y + Math.cos(r) * distNm };
}

/**
 * Perpendicular distance from `p` to the infinite line through `origin` on
 * true bearing `courseDeg`. Positive means `p` lies to the right of the
 * course when looking along it — the sign a localiser deviation needs.
 */
export function crossTrackNm(p: Point, origin: Point, courseDeg: number): number {
  const r = toRadians(courseDeg);
  const dx = p.x - origin.x;
  const dy = p.y - origin.y;
  // Course unit vector is (sin r, cos r); its right-hand normal is (cos r, -sin r).
  return dx * Math.cos(r) - dy * Math.sin(r);
}

/**
 * Distance from `origin` measured along the course through it. Positive is
 * ahead along `courseDeg`, negative behind.
 */
export function alongTrackNm(p: Point, origin: Point, courseDeg: number): number {
  const r = toRadians(courseDeg);
  return (p.x - origin.x) * Math.sin(r) + (p.y - origin.y) * Math.cos(r);
}

/** True bearing to magnetic bearing. `variationDeg` is positive east. */
export function trueToMagnetic(trueDeg: number, variationDeg: number): number {
  return normalizeDeg(trueDeg - variationDeg);
}

/** Magnetic bearing to true bearing. `variationDeg` is positive east. */
export function magneticToTrue(magneticDeg: number, variationDeg: number): number {
  return normalizeDeg(magneticDeg + variationDeg);
}

/** Is `p` inside the polygon? Ray casting; the polygon is treated as closed. */
export function pointInPolygon(p: Point, polygon: readonly Point[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i];
    const b = polygon[j];
    if (a === undefined || b === undefined) continue;
    const intersects =
      a.y > p.y !== b.y > p.y && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x;
    if (intersects) inside = !inside;
  }
  return inside;
}

/** Format a bearing for display, always three digits. */
export function formatBearing(deg: number): string {
  const d = Math.round(normalizeDeg(deg)) % 360;
  return String(d === 0 ? 360 : d).padStart(3, '0');
}
