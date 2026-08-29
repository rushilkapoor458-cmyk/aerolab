/**
 * ILS geometry: where the aircraft is relative to the localiser and the
 * glideslope, whether it may capture either, and whether the approach is
 * stable enough to continue.
 *
 * All of this is pure geometry against the runway threshold, so a bad
 * intercept produces the real result — the aircraft goes straight through the
 * centreline — rather than being magnetised onto it.
 */

import { Approach, Runway } from './airspace.js';
import { alongTrackNm, angleDiff, crossTrackNm, normalizeDeg } from './geo.js';
import { Aircraft } from './types.js';
import { FT_PER_NM, clamp, toRadians } from './units.js';

/** Height of the glidepath above the threshold at the threshold itself. */
export const THRESHOLD_CROSSING_HEIGHT_FT = 50;
/** Altitude above the aerodrome at which the approach must be stable. */
export const STABILITY_GATE_AGL_FT = 1000;
/** Height above the threshold at which the aircraft is considered down. */
export const TOUCHDOWN_HEIGHT_FT = 25;
/** Full scale localiser deflection, degrees either side of the course. */
export const LOCALISER_HALF_ANGLE_DEG = 2.5;

export interface LocaliserGeometry {
  /** Distance to the threshold along the localiser course, NM. Positive ahead. */
  readonly distanceToThresholdNm: number;
  /** Displacement from the centreline, NM. Positive means right of course. */
  readonly crossTrackNm: number;
  /** Signed angle between the aircraft's ground track and the course. */
  readonly interceptAngleDeg: number;
  /** Altitude of the glidepath at this distance, feet AMSL. */
  readonly glideslopeAltitudeFt: number;
  /** How far above the glidepath the aircraft is, feet. Negative is below. */
  readonly aboveGlideslopeFt: number;
  /** Height above the runway threshold, feet. */
  readonly heightAboveThresholdFt: number;
}

export function localiserGeometry(
  ac: Aircraft,
  runway: Runway,
  approach: Approach,
): LocaliserGeometry {
  const course = runway.trueHeadingDeg;
  // The course points along the landing direction, so an aircraft on final
  // sits behind the threshold and its along-track value is negative.
  const along = alongTrackNm(ac.position, runway.threshold, course);
  const distance = -along;
  const cross = crossTrackNm(ac.position, runway.threshold, course);
  const glideslopeAltitude =
    runway.thresholdElevationFt +
    THRESHOLD_CROSSING_HEIGHT_FT +
    Math.max(0, distance) * FT_PER_NM * Math.tan(toRadians(approach.glideslopeAngleDeg));

  return {
    distanceToThresholdNm: distance,
    crossTrackNm: cross,
    interceptAngleDeg: angleDiff(course, ac.trueTrackDeg),
    glideslopeAltitudeFt: glideslopeAltitude,
    aboveGlideslopeFt: ac.altitudeFt - glideslopeAltitude,
    heightAboveThresholdFt: ac.altitudeFt - runway.thresholdElevationFt,
  };
}

/** Half width of the localiser beam at a given range, in nautical miles. */
export function localiserHalfWidthNm(distanceNm: number): number {
  return Math.max(0.35, Math.abs(distanceNm) * Math.tan(toRadians(LOCALISER_HALF_ANGLE_DEG)));
}

/**
 * Whether the aircraft may capture the localiser now.
 *
 * Three things have to be true at once, which is exactly the briefing: inside
 * the intercept range, within the maximum intercept angle, and inside the
 * beam. Miss any of them and the aircraft flies straight through.
 */
export function canCaptureLocaliser(geo: LocaliserGeometry, approach: Approach): boolean {
  if (geo.distanceToThresholdNm <= 0.4) return false;
  if (geo.distanceToThresholdNm > approach.interceptRangeNm) return false;
  if (Math.abs(geo.interceptAngleDeg) > approach.maxInterceptAngleDeg) return false;
  return Math.abs(geo.crossTrackNm) <= localiserHalfWidthNm(geo.distanceToThresholdNm);
}

/** Deviation from the glidepath at which it can be captured, in degrees. */
export const GLIDESLOPE_CAPTURE_HALF_ANGLE_DEG = 0.4;

/**
 * Whether the glideslope may be captured. Only ever from below, and only once
 * the path has come down to within about a dot of the aircraft: an aircraft
 * held high has nothing to capture and will stay high, and one held far below
 * has to wait for the path to reach it.
 */
export function canCaptureGlideslope(geo: LocaliserGeometry, localiserCaptured: boolean): boolean {
  if (!localiserCaptured) return false;
  if (geo.distanceToThresholdNm <= 0.3) return false;
  if (geo.distanceToThresholdNm > 16) return false;
  const window = Math.max(
    80,
    geo.distanceToThresholdNm * FT_PER_NM * Math.tan(toRadians(GLIDESLOPE_CAPTURE_HALF_ANGLE_DEG)),
  );
  return geo.aboveGlideslopeFt <= 60 && geo.aboveGlideslopeFt >= -window;
}

/**
 * Track to fly to stay on the centreline: the course, plus a correction
 * proportional to how far off it the aircraft is.
 */
export function localiserTrackTrueDeg(geo: LocaliserGeometry, courseTrueDeg: number): number {
  const correction = clamp(-geo.crossTrackNm * 12, -25, 25);
  return normalizeDeg(courseTrueDeg + correction);
}

/** Rate of descent that flies the glidepath, with a correction for deviation. */
export function glideslopeVerticalSpeedFpm(
  geo: LocaliserGeometry,
  groundspeedKt: number,
  glideslopeAngleDeg: number,
): number {
  const nominal = -(groundspeedKt * Math.tan(toRadians(glideslopeAngleDeg)) * FT_PER_NM) / 60;
  const correction = clamp(-geo.aboveGlideslopeFt * 12, -500, 500);
  return nominal + correction;
}

/**
 * Where an assigned approach speed is released if the controller named no
 * distance: close enough in that the aircraft can still be configured and
 * stable by the gate, and no closer.
 */
export const DEFAULT_SPEED_RELEASE_NM = 4;

/**
 * Speed to fly on the approach.
 *
 * Left alone, the aircraft manages its own: cruise speed until ten miles,
 * then progressively back to the type's final approach speed. Assign a speed
 * after clearing it for the approach and it holds that instead, until the
 * distance at which it is released — which is how spacing on final is
 * actually worked. Hold one fast too long and it will not be stable at the
 * gate, and it will go around.
 */
export function approachSpeedKt(ac: Aircraft, distanceToThresholdNm: number): number {
  const final = ac.profile.speeds.approachIasKt;
  const clean = ac.profile.speeds.minCleanIasKt;

  if (ac.clearance.speedAssignedOnApproach) {
    const release = ac.clearance.speedReleaseDistanceNm ?? DEFAULT_SPEED_RELEASE_NM;
    if (distanceToThresholdNm > release) {
      return clamp(ac.clearance.speedKt, final, ac.profile.speeds.maxIasKt);
    }
    // Released: the crew slow for landing at their own discretion.
    return final;
  }

  if (distanceToThresholdNm > 10) return Math.min(ac.clearance.speedKt, clean + 30);
  if (distanceToThresholdNm > 5) return clean;
  return final;
}

export interface StabilityResult {
  readonly stable: boolean;
  /** Why it is not stable, phrased the way the crew would say it. */
  readonly reason: string | null;
}

/**
 * The stability gate. Called once, as the aircraft passes 1000 ft above the
 * threshold: off the centreline, off the slope, or too fast means a go-around.
 */
export function checkStability(
  ac: Aircraft,
  geo: LocaliserGeometry,
  runwayOccupied: boolean,
): StabilityResult {
  if (runwayOccupied) return { stable: false, reason: 'the runway is still occupied' };
  if (!ac.approach?.localiserCaptured) return { stable: false, reason: 'we never got the localiser' };
  if (!ac.approach?.glideslopeCaptured) return { stable: false, reason: 'we are not on the glideslope' };
  if (Math.abs(geo.crossTrackNm) > 0.3) return { stable: false, reason: 'we are not lined up' };
  if (Math.abs(geo.aboveGlideslopeFt) > 200) {
    return {
      stable: false,
      reason: geo.aboveGlideslopeFt > 0 ? 'we are high on the slope' : 'we are low on the slope',
    };
  }
  if (ac.iasKt > ac.profile.speeds.approachIasKt + 25) {
    return { stable: false, reason: 'we are too fast to be stable' };
  }
  return { stable: true, reason: null };
}
