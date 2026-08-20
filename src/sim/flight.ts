/**
 * Flight dynamics: turn geometry, the wind triangle, vertical and speed
 * behaviour. Pure functions plus one integrator, no DOM, no globals.
 *
 * Every rate comes from the aircraft's own performance profile and its
 * current mass — see `performance.ts` and `src/data/aircraft.json`.
 */

import { Point, angleDiff, movePoint, normalizeDeg } from './geo.js';
import {
  AircraftProfile,
  accelerationKtPerSec,
  climbRateFpm,
  descentRateFpm,
} from './performance.js';
import { Aircraft, SteeringCommand } from './types.js';
import { approach, clamp, iasToTas, toDegrees, toRadians } from './units.js';

/** Maximum bank the autoflight system will use. */
export const MAX_BANK_DEG = 25;
/** Rate of change of bank angle, degrees per second. */
export const ROLL_RATE_DEG_PER_SEC = 3;
/** Standard rate turn. */
export const STANDARD_TURN_RATE_DEG_PER_SEC = 3;
/** Radar sweep period; one history dot is laid down per sweep. */
export const RADAR_SWEEP_SEC = 4;
export const HISTORY_DOTS = 5;
/** How fast vertical speed itself may change, feet per minute per second. */
export const VERTICAL_ACCEL_FPM_PER_SEC = 400;

/** The 250 kt below 10,000 ft rule. */
export const SPEED_LIMIT_KT = 250;
export const SPEED_LIMIT_ALTITUDE_FT = 10000;

export interface Wind {
  /** Direction the wind blows FROM, in TRUE degrees. */
  readonly fromTrueDeg: number;
  readonly speedKt: number;
}

export interface WindTriangle {
  /** Ground track in true degrees. */
  readonly trackTrueDeg: number;
  readonly groundspeedKt: number;
}

/**
 * Bank angle needed to hold a given turn rate at a given true airspeed.
 *
 * From the level turn relation `tan(bank) = omega * V / g`, with the constant
 * folded into knots and degrees per second: `tan(bank) = omega * V / 1091`.
 */
export function bankForTurnRate(turnRateDegPerSec: number, tasKt: number): number {
  if (tasKt <= 0) return 0;
  return toDegrees(Math.atan((turnRateDegPerSec * tasKt) / 1091));
}

/** Turn rate produced by a bank angle at a given true airspeed. */
export function turnRateForBank(bankDeg: number, tasKt: number): number {
  if (tasKt <= 0) return 0;
  return (1091 * Math.tan(toRadians(bankDeg))) / tasKt;
}

/**
 * Bank the autoflight will use for a turn: standard rate, but never more
 * than {@link MAX_BANK_DEG}, so fast aircraft turn wider than 3 degrees a
 * second exactly as they do in life.
 */
export function commandedBankDeg(tasKt: number): number {
  return Math.min(MAX_BANK_DEG, bankForTurnRate(STANDARD_TURN_RATE_DEG_PER_SEC, tasKt));
}

/** Radius of a level turn, nautical miles. */
export function turnRadiusNm(bankDeg: number, tasKt: number): number {
  const rate = turnRateForBank(bankDeg, tasKt);
  if (rate <= 0) return Infinity;
  // A full circle takes 360/rate seconds and covers tas * that / 3600 NM.
  return (tasKt * (360 / rate)) / 3600 / (2 * Math.PI);
}

/**
 * Signed heading change to fly from `current` to `target` honouring an
 * instructed turn direction. `shortest` takes the near way round; `left` and
 * `right` take the long way when that is the side the controller named.
 */
export function signedTurn(
  currentDeg: number,
  targetDeg: number,
  direction: 'left' | 'right' | 'shortest',
): number {
  const shortest = angleDiff(currentDeg, targetDeg);
  if (direction === 'shortest') return shortest;
  if (direction === 'right') return shortest >= 0 ? shortest : shortest + 360;
  return shortest <= 0 ? shortest : shortest - 360;
}

/**
 * Heading change that will be flown off during roll-out from `bankDeg`.
 * The autoflight starts rolling out this far before the target heading, which
 * is what stops it overshooting.
 */
export function rollOutAnticipationDeg(bankDeg: number, tasKt: number): number {
  const rate = Math.abs(turnRateForBank(bankDeg, tasKt));
  const rollOutSec = Math.abs(bankDeg) / ROLL_RATE_DEG_PER_SEC;
  // Turn rate falls roughly linearly to zero as the wings come level.
  return (rate / 2) * rollOutSec;
}

/** Ground track and groundspeed for an aircraft pointing along a true heading. */
export function windTriangle(headingTrueDeg: number, tasKt: number, wind: Wind): WindTriangle {
  const h = toRadians(headingTrueDeg);
  const airX = Math.sin(h) * tasKt;
  const airY = Math.cos(h) * tasKt;
  // The wind blows towards the reciprocal of the direction it comes from.
  const w = toRadians(wind.fromTrueDeg + 180);
  const gx = airX + Math.sin(w) * wind.speedKt;
  const gy = airY + Math.cos(w) * wind.speedKt;
  return {
    trackTrueDeg: normalizeDeg(toDegrees(Math.atan2(gx, gy))),
    groundspeedKt: Math.hypot(gx, gy),
  };
}

/**
 * True heading to fly in order to make good a desired true track — the crab
 * angle. Returns null when the wind is too strong for the track to be held,
 * which the caller treats as "point at it and accept the drift".
 */
export function headingForTrack(
  desiredTrackTrueDeg: number,
  tasKt: number,
  wind: Wind,
): number | null {
  if (tasKt <= 0) return null;
  // Component of the wind across the desired track, positive from the right.
  const relative = toRadians(wind.fromTrueDeg - desiredTrackTrueDeg);
  const crossWind = wind.speedKt * Math.sin(relative);
  const sinDrift = crossWind / tasKt;
  if (Math.abs(sinDrift) >= 1) return null;
  return normalizeDeg(desiredTrackTrueDeg + toDegrees(Math.asin(sinDrift)));
}

/** The speed the aircraft will actually fly, after its envelope and the rules. */
export function effectiveTargetSpeedKt(ac: Aircraft): number {
  const profile = ac.profile;
  // Configured for an approach, the aircraft may fly below its clean minimum.
  const floor = ac.approach === null ? profile.speeds.minCleanIasKt : profile.speeds.approachIasKt;
  const requested = clamp(ac.clearance.speedKt, floor, profile.speeds.maxIasKt);
  if (ac.clearance.speedRestrictionCancelled) return requested;
  if (ac.altitudeFt < SPEED_LIMIT_ALTITUDE_FT) return Math.min(requested, SPEED_LIMIT_KT);
  return requested;
}

/** Vertical rate the aircraft can make right now, signed, feet per minute. */
export function availableVerticalRateFpm(
  profile: AircraftProfile,
  altitudeFt: number,
  massKg: number,
  climbing: boolean,
  expedite: boolean,
  decelerationDemandKt: number,
): number {
  return climbing
    ? climbRateFpm(profile, altitudeFt, massKg, expedite)
    : descentRateFpm(profile, altitudeFt, massKg, expedite, decelerationDemandKt);
}

export interface StepContext {
  /** The wind at a given altitude, direction FROM in true degrees. */
  readonly windAt: (altitudeFt: number) => Wind;
  /** Magnetic variation, positive east, used to turn headings into tracks. */
  readonly magneticVariationDeg: number;
}

/**
 * Advance one aircraft by `dtSec`, flying the steering command the autoflight
 * produced. Where the command leaves a field null the aircraft falls back to
 * its clearance — a heading and a cleared level.
 */
export function stepAircraft(
  ac: Aircraft,
  command: SteeringCommand,
  dtSec: number,
  ctx: StepContext,
): void {
  const profile = ac.profile;
  const targetHeadingDeg = command.headingDeg;
  const tas = iasToTas(ac.iasKt, ac.altitudeFt);

  // ---- lateral: roll, turn, roll out -------------------------------------
  if (targetHeadingDeg !== null) {
    // A named turn commits to a direction and a number of degrees; anything
    // else simply steers the short way round to whatever the target is now.
    const latched = ac.clearance.turnRemainingDeg;
    const delta = latched ?? angleDiff(ac.headingDeg, targetHeadingDeg);

    const maxBank = commandedBankDeg(tas);
    const anticipation = rollOutAnticipationDeg(Math.min(Math.abs(ac.bankDeg) || maxBank, maxBank), tas);
    const wantBank = Math.abs(delta) <= anticipation ? 0 : Math.sign(delta) * maxBank;
    ac.bankDeg = approach(ac.bankDeg, wantBank, ROLL_RATE_DEG_PER_SEC * dtSec);

    const turnRate = turnRateForBank(ac.bankDeg, tas);
    const before = ac.headingDeg;
    ac.headingDeg = normalizeDeg(before + turnRate * dtSec);
    if (latched !== null) {
      ac.clearance.turnRemainingDeg = latched - angleDiff(before, ac.headingDeg);
    }

    // Settle exactly on the assigned heading once the turn has run out.
    const remaining = ac.clearance.turnRemainingDeg ?? angleDiff(ac.headingDeg, targetHeadingDeg);
    if (Math.abs(remaining) < 0.4 && Math.abs(ac.bankDeg) < 1.5) {
      ac.headingDeg = normalizeDeg(targetHeadingDeg);
      ac.bankDeg = 0;
      ac.clearance.turnRemainingDeg = null;
      // A named turn direction is spent once the heading is reached.
      if (ac.clearance.turn !== 'shortest') ac.clearance.turn = 'shortest';
    }
  } else {
    ac.bankDeg = approach(ac.bankDeg, 0, ROLL_RATE_DEG_PER_SEC * dtSec);
  }

  // ---- speed target ------------------------------------------------------
  const targetIas =
    command.speedKt === null
      ? effectiveTargetSpeedKt(ac)
      : clamp(command.speedKt, profile.speeds.approachIasKt, profile.speeds.maxIasKt);
  const decelerationDemand = Math.max(0, ac.iasKt - targetIas);

  // ---- vertical ----------------------------------------------------------
  if (command.verticalSpeedFpm === null) {
    const altError = ac.clearance.altitudeFt - ac.altitudeFt;
    const climbing = altError > 0;
    const nominal = availableVerticalRateFpm(
      profile,
      ac.altitudeFt,
      ac.massKg,
      climbing,
      ac.clearance.expedite,
      decelerationDemand,
    );
    // Ease off approaching the cleared level so the capture is not a corner.
    const captureLimit = Math.abs(altError) * 6;
    const targetVs = Math.sign(altError) * Math.min(nominal, captureLimit);
    ac.verticalSpeedFpm = approach(ac.verticalSpeedFpm, targetVs, VERTICAL_ACCEL_FPM_PER_SEC * dtSec);
    ac.altitudeFt += (ac.verticalSpeedFpm / 60) * dtSec;
    if (Math.abs(ac.clearance.altitudeFt - ac.altitudeFt) < 5 && Math.abs(ac.verticalSpeedFpm) < 150) {
      ac.altitudeFt = ac.clearance.altitudeFt;
      ac.verticalSpeedFpm = 0;
    }
  } else {
    // Flying a profile — the glideslope — rather than levelling off.
    const maximum = availableVerticalRateFpm(profile, ac.altitudeFt, ac.massKg, false, false, 0);
    const wanted = clamp(command.verticalSpeedFpm, -maximum, maximum);
    ac.verticalSpeedFpm = approach(ac.verticalSpeedFpm, wanted, VERTICAL_ACCEL_FPM_PER_SEC * dtSec);
    ac.altitudeFt += (ac.verticalSpeedFpm / 60) * dtSec;
  }

  // The approach phase is set by the approach logic, not by the trend arrow.
  if (ac.phase !== 'approach') {
    ac.phase =
      ac.verticalSpeedFpm > 200 ? 'climb' : ac.verticalSpeedFpm < -200 ? 'descent' : 'cruise';
  }

  // ---- speed -------------------------------------------------------------
  const accelerating = targetIas > ac.iasKt;
  const limit = accelerationKtPerSec(profile, ac.phase, accelerating, ac.bankDeg);
  ac.iasKt = approach(ac.iasKt, targetIas, limit * dtSec);

  // ---- move --------------------------------------------------------------
  const tasNow = iasToTas(ac.iasKt, ac.altitudeFt);
  const headingTrue = normalizeDeg(ac.headingDeg + ctx.magneticVariationDeg);
  const triangle = windTriangle(headingTrue, tasNow, ctx.windAt(ac.altitudeFt));
  ac.trueTrackDeg = triangle.trackTrueDeg;
  ac.groundspeedKt = triangle.groundspeedKt;
  ac.position = movePoint(ac.position, ac.trueTrackDeg, (ac.groundspeedKt / 3600) * dtSec);

  // ---- radar sweep -------------------------------------------------------
  ac.sweepTimerSec -= dtSec;
  if (ac.sweepTimerSec <= 0) {
    ac.sweepTimerSec += RADAR_SWEEP_SEC;
    ac.history.push(ac.position);
    while (ac.history.length > HISTORY_DOTS) ac.history.shift();
  }
}

/** Where an aircraft will be in `sec` seconds if nothing changes. */
export function projectPosition(ac: Aircraft, sec: number): Point {
  return movePoint(ac.position, ac.trueTrackDeg, (ac.groundspeedKt / 3600) * sec);
}
