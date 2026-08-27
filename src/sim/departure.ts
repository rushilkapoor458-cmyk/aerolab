/**
 * Departures: the runway queue and the take-off roll.
 *
 * Taxi is abstracted — an aircraft appears at the holding point ready to go.
 * From "line up and wait" onwards it is modelled properly: it accelerates
 * along the runway at its own rate and rotates at its own speed.
 */

import { Runway } from './airspace.js';
import { movePoint, normalizeDeg } from './geo.js';
import { AircraftProfile } from './performance.js';
import { Wind } from './flight.js';
import { Aircraft } from './types.js';
import { iasToTas, toRadians } from './units.js';

/** Acceleration on the take-off roll, knots per second. */
export function takeoffAccelerationKtPerSec(profile: AircraftProfile): number {
  switch (profile.engine) {
    case 'jet':
      return 3.4;
    case 'turboprop':
      return 3.0;
    default:
      return 2.0;
  }
}

/**
 * Rotation speed. Approach speed is close to the landing reference speed, and
 * a departure rotates a little above it — near enough for this simulation.
 */
export function rotationSpeedKt(profile: AircraftProfile): number {
  return profile.speeds.approachIasKt + 20;
}

/** Speed at which the aircraft is cleaned up and accelerating away. */
export function initialClimbSpeedKt(profile: AircraftProfile): number {
  return Math.max(profile.speeds.approachIasKt + 40, profile.speeds.minCleanIasKt);
}

/** Put a departure at the holding point of its runway, ready to go. */
export function placeAtHoldingPoint(ac: Aircraft, runway: Runway, magneticVariationDeg: number): void {
  ac.ground = 'queue';
  ac.departureRunway = runway.ident;
  ac.position = runway.threshold;
  ac.altitudeFt = runway.thresholdElevationFt;
  ac.headingDeg = normalizeDeg(runway.trueHeadingDeg - magneticVariationDeg);
  ac.trueTrackDeg = runway.trueHeadingDeg;
  ac.iasKt = 0;
  ac.groundspeedKt = 0;
  ac.verticalSpeedFpm = 0;
  ac.clearance.headingDeg = ac.headingDeg;
  ac.clearance.speedKt = initialClimbSpeedKt(ac.profile);
}

export interface GroundStepContext {
  readonly wind: Wind;
  readonly magneticVariationDeg: number;
  readonly runway: Runway;
}

export interface GroundStepResult {
  /** True on the step the aircraft leaves the ground. */
  readonly airborne: boolean;
}

/**
 * Advance an aircraft that is still on the runway. Queued and lined-up
 * aircraft do not move; one that is rolling accelerates and eventually flies.
 */
export function stepGroundRoll(ac: Aircraft, dtSec: number, ctx: GroundStepContext): GroundStepResult {
  if (ac.ground !== 'takeoff') return { airborne: false };

  const rotate = rotationSpeedKt(ac.profile);
  ac.iasKt = Math.min(rotate + 5, ac.iasKt + takeoffAccelerationKtPerSec(ac.profile) * dtSec);

  // On the ground the aircraft runs along the runway, so its track is the
  // runway course and the wind only changes how fast the ground goes past.
  const tas = iasToTas(ac.iasKt, ac.altitudeFt);
  const headwind =
    ctx.wind.speedKt * Math.cos(toRadians(ctx.wind.fromTrueDeg - ctx.runway.trueHeadingDeg));
  const groundspeed = Math.max(0, tas - headwind);
  ac.trueTrackDeg = ctx.runway.trueHeadingDeg;
  ac.groundspeedKt = groundspeed;
  ac.position = movePoint(ac.position, ac.trueTrackDeg, (groundspeed / 3600) * dtSec);

  if (ac.iasKt < rotate) return { airborne: false };

  // Rotation: the aircraft is flying from here on.
  ac.ground = null;
  ac.phase = 'climb';
  ac.verticalSpeedFpm = 0;
  ac.clearance.speedKt = initialClimbSpeedKt(ac.profile);
  return { airborne: true };
}
