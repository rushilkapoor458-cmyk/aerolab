/**
 * Flight dynamics: turn geometry, the wind triangle, vertical and speed
 * behaviour. Pure functions plus one integrator, no DOM, no globals.
 *
 * Milestone 1 uses one generic transport-category envelope. Milestone 2
 * replaces the constants marked GENERIC below with per-type performance
 * profiles; nothing else in this file changes shape.
 */

import { Point, angleDiff, movePoint, normalizeDeg } from './geo.js';
import { Aircraft, FlightPhase } from './types.js';
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

/** GENERIC envelope, replaced per type in milestone 2. */
export const GENERIC = {
  minSpeedKt: 140,
  maxSpeedKt: 320,
  climbRateFpm: 2000,
  descentRateFpm: 1800,
  expediteClimbRateFpm: 2800,
  expediteDescentRateFpm: 2600,
  /** How fast vertical speed itself may change, fpm per second. */
  verticalAccelFpmPerSec: 400,
} as const;

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

/** The speed the aircraft will actually fly, after the 250/10,000 rule. */
export function effectiveTargetSpeedKt(ac: Aircraft): number {
  const requested = clamp(ac.clearance.speedKt, GENERIC.minSpeedKt, GENERIC.maxSpeedKt);
  if (ac.clearance.speedRestrictionCancelled) return requested;
  if (ac.altitudeFt < SPEED_LIMIT_ALTITUDE_FT) return Math.min(requested, SPEED_LIMIT_KT);
  return requested;
}

/** Longitudinal acceleration available, knots per second, signed. */
export function accelerationLimitKtPerSec(
  accelerating: boolean,
  phase: FlightPhase,
  bankDeg: number,
): number {
  let limit: number;
  if (accelerating) {
    limit = phase === 'climb' ? 0.5 : phase === 'descent' ? 1.4 : 1.0;
    // Induced drag in a turn eats into whatever thrust is spare.
    if (Math.abs(bankDeg) > 15) limit = Math.max(0.1, limit - 0.4);
  } else {
    // Slowing down in a descent is the hard case: idle thrust is already set.
    limit = phase === 'climb' ? 1.8 : phase === 'descent' ? 1.0 : 1.5;
  }
  return limit;
}

export interface StepContext {
  readonly wind: Wind;
  /** Magnetic variation, positive east, used to turn headings into tracks. */
  readonly magneticVariationDeg: number;
}

/**
 * Advance one aircraft by `dtSec`. The caller has already resolved the
 * autoflight targets into `ac.clearance` and `ac.headingDeg`'s target.
 *
 * `targetHeadingDeg` is magnetic; passing null holds the current heading.
 */
export function stepAircraft(
  ac: Aircraft,
  targetHeadingDeg: number | null,
  dtSec: number,
  ctx: StepContext,
): void {
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

  // ---- vertical ----------------------------------------------------------
  const altError = ac.clearance.altitudeFt - ac.altitudeFt;
  const climbing = altError > 0;
  const nominal = climbing
    ? ac.clearance.expedite
      ? GENERIC.expediteClimbRateFpm
      : GENERIC.climbRateFpm
    : ac.clearance.expedite
      ? GENERIC.expediteDescentRateFpm
      : GENERIC.descentRateFpm;
  // Ease off approaching the cleared level so the capture is not a corner.
  const captureLimit = Math.abs(altError) * 6;
  const targetVs = Math.sign(altError) * Math.min(nominal, captureLimit);
  ac.verticalSpeedFpm = approach(
    ac.verticalSpeedFpm,
    targetVs,
    GENERIC.verticalAccelFpmPerSec * dtSec,
  );
  ac.altitudeFt += (ac.verticalSpeedFpm / 60) * dtSec;
  if (Math.abs(ac.clearance.altitudeFt - ac.altitudeFt) < 5 && Math.abs(ac.verticalSpeedFpm) < 150) {
    ac.altitudeFt = ac.clearance.altitudeFt;
    ac.verticalSpeedFpm = 0;
  }

  ac.phase =
    ac.verticalSpeedFpm > 200 ? 'climb' : ac.verticalSpeedFpm < -200 ? 'descent' : 'cruise';

  // ---- speed -------------------------------------------------------------
  const targetIas = effectiveTargetSpeedKt(ac);
  const accelerating = targetIas > ac.iasKt;
  const limit = accelerationLimitKtPerSec(accelerating, ac.phase, ac.bankDeg);
  ac.iasKt = approach(ac.iasKt, targetIas, limit * dtSec);

  // ---- move --------------------------------------------------------------
  const tasNow = iasToTas(ac.iasKt, ac.altitudeFt);
  const headingTrue = normalizeDeg(ac.headingDeg + ctx.magneticVariationDeg);
  const triangle = windTriangle(headingTrue, tasNow, ctx.wind);
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
