/**
 * Autoflight: turns a clearance into what the aeroplane should actually do —
 * a heading to steer, and where required a vertical speed and a speed that
 * override the controller's assigned figures.
 *
 * Four lateral modes. On `heading` the aircraft points at the assigned
 * magnetic heading and lets the wind drift it, which is why vectors need an
 * allowance for drift. On `direct` it tracks a fix, computing its own crab
 * angle. On `hold` it flies the published racetrack. On `approach` it is
 * flying an ILS — and only captures it if the intercept was a good one.
 */

import { Airspace } from './airspace.js';
import { bearingDeg, distanceNm, normalizeDeg } from './geo.js';
import { Wind, headingForTrack } from './flight.js';
import {
  approachSpeedKt,
  canCaptureGlideslope,
  canCaptureLocaliser,
  checkStability,
  glideslopeVerticalSpeedFpm,
  localiserGeometry,
  localiserTrackTrueDeg,
  STABILITY_GATE_AGL_FT,
  TOUCHDOWN_HEIGHT_FT,
} from './approach.js';
import { holdingSpeedKt, stepHold } from './hold.js';
import { Aircraft, SteeringCommand } from './types.js';
import { formatHhmm, iasToTas } from './units.js';

export interface AutoflightResult {
  readonly command: SteeringCommand;
  /** Things the crew would say. */
  readonly reports: readonly string[];
  /** True on the step the aircraft touches down. */
  readonly landed: boolean;
  /** True on the step the aircraft goes around. */
  readonly wentAround: boolean;
}

export interface NavContext {
  readonly airspace: Airspace;
  readonly wind: Wind;
  readonly dtSec: number;
  readonly timeSec: number;
  readonly isRunwayOccupied: (ident: string) => boolean;
}

/** Distance at which a fix counts as overflown, in nautical miles. */
export function fixCaptureRadiusNm(groundspeedKt: number): number {
  // Roughly ten seconds of flying, never less than half a mile.
  return Math.max(0.5, (groundspeedKt / 3600) * 10);
}

/** Heading, in magnetic degrees, that makes good a true track in this wind. */
function headingForTrackMagnetic(ac: Aircraft, trackTrueDeg: number, ctx: NavContext): number {
  const tas = iasToTas(ac.iasKt, ac.altitudeFt);
  const headingTrue = headingForTrack(trackTrueDeg, tas, ctx.wind) ?? trackTrueDeg;
  return normalizeDeg(headingTrue - ctx.airspace.airport.magneticVariationDeg);
}

function steer(ac: Aircraft, headingDeg: number | null): SteeringCommand {
  if (headingDeg !== null) ac.clearance.headingDeg = headingDeg;
  return { headingDeg, verticalSpeedFpm: null, speedKt: null };
}

export function updateAutoflight(ac: Aircraft, ctx: NavContext): AutoflightResult {
  const reports: string[] = [];

  if (ac.approach !== null) return flyApproach(ac, ctx, reports);
  if (ac.clearance.lateralMode === 'hold' && ac.hold !== null) return flyHold(ac, ctx, reports);
  if (ac.clearance.lateralMode === 'direct' && ac.clearance.directFix !== null) {
    return flyRoute(ac, ctx, reports);
  }
  return plain(steer(ac, ac.clearance.headingDeg), reports);
}

function plain(command: SteeringCommand, reports: readonly string[]): AutoflightResult {
  return { command, reports, landed: false, wentAround: false };
}

/* ------------------------------------------------------------------ route */

function flyRoute(ac: Aircraft, ctx: NavContext, reports: string[]): AutoflightResult {
  const current = ac.clearance.directFix;
  if (current === null) return plain(steer(ac, ac.clearance.headingDeg), reports);

  const fix = ctx.airspace.fix(current);
  if (fix === undefined) {
    ac.clearance.lateralMode = 'heading';
    ac.clearance.directFix = null;
    reports.push(`unable, we do not have ${current} in the database, maintaining present heading`);
    return plain(steer(ac, ac.headingDeg), reports);
  }

  if (distanceNm(ac.position, fix.position) <= fixCaptureRadiusNm(ac.groundspeedKt)) {
    sequenceToNextFix(ac, ctx, fix.name, reports);
    if (ac.clearance.directFix === null) return plain(steer(ac, ac.headingDeg), reports);
  }

  const target = ctx.airspace.fix(ac.clearance.directFix ?? '');
  if (target === undefined) return plain(steer(ac, ac.clearance.headingDeg), reports);

  const heading = headingForTrackMagnetic(ac, bearingDeg(ac.position, target.position), ctx);
  ac.clearance.turnRemainingDeg = null;
  return plain(steer(ac, heading), reports);
}

/**
 * Move on to the next fix of the route, applying that leg's published
 * restrictions if the aircraft has been cleared to descend via the arrival.
 */
function sequenceToNextFix(
  ac: Aircraft,
  ctx: NavContext,
  passedFix: string,
  reports: string[],
): void {
  const next = ac.route.shift();
  if (next === undefined || ctx.airspace.fix(next) === undefined) {
    ac.clearance.lateralMode = 'heading';
    ac.clearance.directFix = null;
    reports.push(`${passedFix} passed, maintaining present heading`);
    return;
  }

  ac.clearance.directFix = next;
  const applied = ac.clearance.descendVia ? applyLegRestrictions(ac, ctx, next) : null;
  reports.push(
    applied === null ? `${passedFix} passed, proceeding ${next}` : `${passedFix} passed, ${applied}`,
  );
}

/** Apply the published restriction at a fix. Returns what the crew would say. */
function applyLegRestrictions(ac: Aircraft, ctx: NavContext, fixName: string): string | null {
  if (ac.procedure === null) return null;
  const leg = ctx.airspace.procedureLeg(ac.procedure, fixName);
  if (leg === undefined) return null;

  const parts: string[] = [];
  if (leg.altitudeConstraint !== null) {
    ac.clearance.altitudeFt = leg.altitudeConstraint.altitudeFt;
    parts.push(`descending to ${leg.altitudeConstraint.altitudeFt} for ${fixName}`);
  }
  if (leg.speedConstraint !== null) {
    ac.clearance.speedKt = leg.speedConstraint.speedKt;
    parts.push(`speed ${leg.speedConstraint.speedKt}`);
  }
  return parts.length === 0 ? null : parts.join(', ');
}

/* ------------------------------------------------------------------- hold */

function flyHold(ac: Aircraft, ctx: NavContext, reports: string[]): AutoflightResult {
  const state = ac.hold;
  if (state === null) return plain(steer(ac, ac.clearance.headingDeg), reports);

  const fix = ctx.airspace.fix(state.fix);
  if (fix === undefined) {
    ac.hold = null;
    ac.clearance.lateralMode = 'heading';
    reports.push(`unable, we do not have ${state.fix} in the database`);
    return plain(steer(ac, ac.headingDeg), reports);
  }

  const atFix = distanceNm(ac.position, fix.position) <= fixCaptureRadiusNm(ac.groundspeedKt);
  const previousLeg = state.leg;
  const steerTo = stepHold(ac, state, atFix, ctx.dtSec);
  if (previousLeg === 'toFix' && state.leg === 'outbound' && !state.established) {
    // Reported on entry only, not on every circuit.
    state.established = true;
    const efc = state.efcTimeSec === null ? '' : `, expecting further clearance at ${formatHhmm(state.efcTimeSec)}`;
    reports.push(`established in the hold at ${state.fix}${efc}`);
  }

  const trackTrue = steerTo.directToFix
    ? bearingDeg(ac.position, fix.position)
    : (steerTo.trackTrueDeg ?? ac.trueTrackDeg);
  const heading = headingForTrackMagnetic(ac, trackTrue, ctx);
  ac.clearance.turn = steerTo.turn;
  if (steerTo.turn === 'shortest') ac.clearance.turnRemainingDeg = null;

  const hold = ctx.airspace.hold(state.fix);
  const speed = hold === undefined ? null : holdingSpeedKt(ac, hold.maxSpeedKt);
  ac.clearance.headingDeg = heading;
  return {
    command: { headingDeg: heading, verticalSpeedFpm: null, speedKt: speed },
    reports,
    landed: false,
    wentAround: false,
  };
}

/* --------------------------------------------------------------- approach */

function flyApproach(ac: Aircraft, ctx: NavContext, reports: string[]): AutoflightResult {
  const state = ac.approach;
  if (state === null) return plain(steer(ac, ac.clearance.headingDeg), reports);

  const runway = ctx.airspace.runway(state.runway);
  const approach = ctx.airspace.approachForRunway(state.runway);
  if (runway === undefined || approach === undefined) {
    ac.approach = null;
    ac.clearance.lateralMode = 'heading';
    reports.push(`unable, we have no approach for runway ${state.runway}`);
    return plain(steer(ac, ac.headingDeg), reports);
  }

  const geo = localiserGeometry(ac, runway, approach);

  // ---- capture, or fly straight through -----------------------------------
  if (!state.localiserCaptured) {
    if (canCaptureLocaliser(geo, approach)) {
      state.localiserCaptured = true;
      ac.clearance.lateralMode = 'approach';
      ac.clearance.turnRemainingDeg = null;
      reports.push(`localiser established, runway ${runway.ident}`);
    } else {
      // A bad intercept is a bad intercept: keep flying the assigned heading
      // and say so as the centreline goes past.
      if (
        !state.reportedBlowThrough &&
        Math.abs(geo.crossTrackNm) > 0.5 &&
        geo.distanceToThresholdNm > 0 &&
        geo.distanceToThresholdNm < approach.interceptRangeNm &&
        Math.abs(geo.interceptAngleDeg) > approach.maxInterceptAngleDeg
      ) {
        state.reportedBlowThrough = true;
        reports.push(`we are going through the localiser for runway ${runway.ident}, say intentions`);
      }
      return plain(steer(ac, ac.clearance.headingDeg), reports);
    }
  }

  // ---- established: track the centreline ----------------------------------
  const track = localiserTrackTrueDeg(geo, runway.trueHeadingDeg);
  const heading = headingForTrackMagnetic(ac, track, ctx);
  ac.clearance.headingDeg = heading;
  ac.phase = 'approach';

  if (!state.glideslopeCaptured && canCaptureGlideslope(geo, state.localiserCaptured)) {
    state.glideslopeCaptured = true;
    // The cleared level no longer means anything once the aircraft is on the
    // path, so the data block shows where it is actually going: the runway.
    ac.clearance.altitudeFt = runway.thresholdElevationFt;
    reports.push('glideslope established');
  }

  const speed = approachSpeedKt(ac, geo.distanceToThresholdNm);
  const verticalSpeed = state.glideslopeCaptured
    ? glideslopeVerticalSpeedFpm(geo, ac.groundspeedKt, approach.glideslopeAngleDeg)
    : null;

  // ---- the stability gate at 1000 ft --------------------------------------
  if (!state.stabilityChecked && geo.heightAboveThresholdFt <= STABILITY_GATE_AGL_FT) {
    state.stabilityChecked = true;
    const stability = checkStability(ac, geo, ctx.isRunwayOccupied(runway.ident));
    if (!stability.stable) {
      return goAround(ac, ctx, runway.ident, stability.reason ?? 'unstable', reports);
    }
  }

  // ---- touchdown, or the missed approach point ----------------------------
  // On a three degree path the aircraft crosses the threshold at fifty feet
  // and settles a few hundred yards down the runway, so the touchdown test is
  // a height test, and the distance may already be slightly negative.
  if (geo.heightAboveThresholdFt <= TOUCHDOWN_HEIGHT_FT && geo.distanceToThresholdNm > -0.8) {
    reports.push(`landing runway ${runway.ident}`);
    return {
      command: { headingDeg: heading, verticalSpeedFpm: verticalSpeed, speedKt: speed },
      reports,
      landed: true,
      wentAround: false,
    };
  }
  if (geo.distanceToThresholdNm <= -0.5) {
    // Half a mile past the threshold and still flying: this is the missed
    // approach, whether or not the gate at 1000 ft caught it first.
    return goAround(ac, ctx, runway.ident, 'we are not in a position to land', reports);
  }

  return {
    command: { headingDeg: heading, verticalSpeedFpm: verticalSpeed, speedKt: speed },
    reports,
    landed: false,
    wentAround: false,
  };
}

/** Abandon the approach: climb away on the runway heading. */
export function goAround(
  ac: Aircraft,
  ctx: NavContext,
  runwayIdent: string,
  reason: string,
  reports: string[],
): AutoflightResult {
  const runway = ctx.airspace.runway(runwayIdent);
  const approach = ctx.airspace.approachForRunway(runwayIdent);
  const missedAltitude = approach?.missedApproachAltitudeFt ?? 4000;

  ac.approach = null;
  ac.goAroundCount += 1;
  ac.phase = 'climb';
  ac.clearance.lateralMode = 'heading';
  ac.clearance.directFix = null;
  ac.clearance.turn = 'shortest';
  ac.clearance.turnRemainingDeg = null;
  ac.clearance.altitudeFt = missedAltitude;
  ac.clearance.expedite = false;
  ac.clearance.speedKt = Math.max(ac.clearance.speedKt, ac.profile.speeds.minCleanIasKt);
  const heading =
    runway === undefined ? ac.headingDeg : ctx.airspace.toMagnetic(runway.trueHeadingDeg);
  ac.clearance.headingDeg = heading;

  reports.push(`going around, ${reason}, climbing ${missedAltitude} on runway heading`);
  return {
    command: { headingDeg: heading, verticalSpeedFpm: null, speedKt: null },
    reports,
    landed: false,
    wentAround: true,
  };
}
