/**
 * Separation standards and conflict prediction.
 *
 * The prediction is the usual short term conflict alert assumption: each
 * aircraft keeps its present ground track and groundspeed, and continues its
 * present climb or descent until it reaches the level it is cleared to. That
 * makes a turning aircraft produce the occasional alert that resolves itself,
 * which is exactly what the real thing does.
 */

import { Point, distanceNm, movePoint } from './geo.js';
import { Aircraft } from './types.js';

export const VERTICAL_SEPARATION_FT = 1000;
/** Radar separation inside the terminal area. */
export const TMA_LATERAL_NM = 3;
/** Radar separation beyond the terminal area. */
export const OUTER_LATERAL_NM = 5;
/** Range from the aerodrome at which the larger minimum takes over. */
export const OUTER_BOUNDARY_NM = 40;

/** How far ahead the conflict alert looks. */
export const LOOKAHEAD_SEC = 120;
/** How finely the look-ahead is sampled. */
export const SAMPLE_STEP_SEC = 5;

export interface SeparationStandard {
  readonly lateralNm: number;
  readonly verticalFt: number;
}

/** Distance of an aircraft from the aerodrome reference point, in NM. */
export function rangeFromFieldNm(ac: Aircraft): number {
  return Math.hypot(ac.position.x, ac.position.y);
}

/**
 * The standard that applies to a pair. The larger minimum applies as soon as
 * either aircraft is outside the terminal area.
 */
export function standardFor(a: Aircraft, b: Aircraft): SeparationStandard {
  const outside = Math.max(rangeFromFieldNm(a), rangeFromFieldNm(b)) > OUTER_BOUNDARY_NM;
  return {
    lateralNm: outside ? OUTER_LATERAL_NM : TMA_LATERAL_NM,
    verticalFt: VERTICAL_SEPARATION_FT,
  };
}

/** Where an aircraft will be in `sec` seconds on its present track. */
export function projectedPosition(ac: Aircraft, sec: number): Point {
  return movePoint(ac.position, ac.trueTrackDeg, (ac.groundspeedKt / 3600) * sec);
}

/**
 * Altitude in `sec` seconds, levelling off at the cleared altitude rather
 * than climbing or descending for ever.
 */
export function projectedAltitudeFt(ac: Aircraft, sec: number): number {
  const raw = ac.altitudeFt + (ac.verticalSpeedFpm / 60) * sec;
  if (ac.verticalSpeedFpm > 0) return Math.min(raw, Math.max(ac.clearance.altitudeFt, ac.altitudeFt));
  if (ac.verticalSpeedFpm < 0) return Math.max(raw, Math.min(ac.clearance.altitudeFt, ac.altitudeFt));
  return ac.altitudeFt;
}

export type ConflictSeverity = 'none' | 'predicted' | 'loss';

export interface ConflictAssessment {
  readonly severity: ConflictSeverity;
  /** Seconds until the minima are first breached, or null if they are not. */
  readonly timeToLossSec: number | null;
  /** Horizontal distance at the closest point examined. */
  readonly closestDistanceNm: number;
  /** Vertical difference at that same moment. */
  readonly closestVerticalFt: number;
  /** When that closest point occurs, in seconds from now. */
  readonly closestAtSec: number;
}

/**
 * Assess one pair. Samples the look-ahead rather than solving analytically,
 * because the vertical profile is piecewise — it stops at the cleared level.
 */
export function assessConflict(
  a: Aircraft,
  b: Aircraft,
  standard: SeparationStandard,
  lookaheadSec: number = LOOKAHEAD_SEC,
  stepSec: number = SAMPLE_STEP_SEC,
): ConflictAssessment {
  let timeToLossSec: number | null = null;
  let closestDistanceNm = Infinity;
  let closestVerticalFt = Infinity;
  let closestAtSec = 0;

  for (let t = 0; t <= lookaheadSec; t += stepSec) {
    const horizontal = distanceNm(projectedPosition(a, t), projectedPosition(b, t));
    const vertical = Math.abs(projectedAltitudeFt(a, t) - projectedAltitudeFt(b, t));

    if (horizontal < closestDistanceNm) {
      closestDistanceNm = horizontal;
      closestVerticalFt = vertical;
      closestAtSec = t;
    }
    if (timeToLossSec === null && horizontal < standard.lateralNm && vertical < standard.verticalFt) {
      timeToLossSec = t;
    }
  }

  const severity: ConflictSeverity =
    timeToLossSec === null ? 'none' : timeToLossSec === 0 ? 'loss' : 'predicted';
  return { severity, timeToLossSec, closestDistanceNm, closestVerticalFt, closestAtSec };
}

/** Present separation between a pair, with no prediction at all. */
export function currentSeparation(a: Aircraft, b: Aircraft): { lateralNm: number; verticalFt: number } {
  return {
    lateralNm: distanceNm(a.position, b.position),
    verticalFt: Math.abs(a.altitudeFt - b.altitudeFt),
  };
}
