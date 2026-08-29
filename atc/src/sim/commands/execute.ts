/**
 * Applying instructions to an aircraft, and the pilot's answer.
 *
 * A pilot reads back what they can comply with and says "unable" — with a
 * reason — to anything they cannot. A transmission may be partly accepted:
 * a descent that goes below the safe altitude is refused while the turn
 * issued in the same breath is flown.
 */

import { Airspace } from '../airspace.js';
import { formatBearing } from '../geo.js';
import { createHoldState } from '../hold.js';
import { SPEED_LIMIT_ALTITUDE_FT, SPEED_LIMIT_KT, signedTurn } from '../flight.js';
import { fuelReport } from '../fuel.js';
import { Aircraft } from '../types.js';
import { formatFlightLevel, formatHhmm } from '../units.js';
import { Command } from './types.js';

export interface ExecutionContext {
  readonly airspace: Airspace;
  /** The runway configuration in use, for departures with no runway named. */
  readonly departureRunway: string;
  /** True while a landing roll or another departure still has the runway. */
  readonly isRunwayOccupied: (ident: string) => boolean;
  /** Hold the runway for a departure that has just been cleared to go. */
  readonly occupyRunway: (ident: string, seconds: number) => void;
  /** Simulation clock, for expect-further-clearance times. */
  readonly timeSec: number;
  /** Send the aircraft around; returns the crew's answer, or null if it is not on one. */
  readonly goAround: (ac: Aircraft, reason: string) => string | null;
}

export interface ExecutionOutcome {
  /** What the pilot says back, already including the callsign. */
  readonly readback: string;
  /** True if any part of the transmission was refused. */
  readonly rejected: boolean;
}

interface SingleOutcome {
  readonly accepted: boolean;
  readonly text: string;
}

/** Buffer between the published minimum safe altitude and a refusal. */
const MSA_BUFFER_FT = 0;

export function executeCommands(
  ac: Aircraft,
  commands: readonly Command[],
  ctx: ExecutionContext,
): ExecutionOutcome {
  const accepted: string[] = [];
  const refused: string[] = [];

  for (const command of commands) {
    const outcome = executeOne(ac, command, ctx);
    if (outcome.accepted) accepted.push(outcome.text);
    else refused.push(outcome.text);
  }

  const parts: string[] = [];
  if (accepted.length > 0) parts.push(accepted.join(', '));
  for (const reason of refused) parts.push(`unable, ${reason}`);
  return { readback: `${parts.join(', ')}, ${ac.callsign}`, rejected: refused.length > 0 };
}

function executeOne(ac: Aircraft, command: Command, ctx: ExecutionContext): SingleOutcome {
  const airspace = ctx.airspace;
  switch (command.kind) {
    case 'heading': {
      if (ac.ground !== null) {
        ac.clearance.headingDeg = command.headingDeg;
        return ok(`after departure, heading ${formatBearing(command.headingDeg)}`);
      }
      leaveProcedures(ac);
      ac.clearance.lateralMode = 'heading';
      ac.clearance.directFix = null;
      ac.clearance.headingDeg = command.headingDeg;
      ac.clearance.turn = command.turn;
      ac.clearance.turnRemainingDeg =
        command.turn === 'shortest'
          ? null
          : signedTurn(ac.headingDeg, command.headingDeg, command.turn);
      const word = command.turn === 'left' ? 'turn left heading' : command.turn === 'right' ? 'turn right heading' : 'fly heading';
      return ok(`${word} ${formatBearing(command.headingDeg)}`);
    }

    case 'altitude':
      return executeAltitude(ac, command, airspace);

    case 'speed': {
      const envelope = ac.profile.speeds;
      // An aircraft on an approach is configuring, so it can fly slower than
      // its clean minimum — down to its final approach speed.
      const floor = ac.approach === null ? envelope.minCleanIasKt : envelope.approachIasKt;
      if (command.speedKt < floor) {
        return no(
          ac.approach === null
            ? `${command.speedKt} knots is below our minimum clean speed of ${envelope.minCleanIasKt}`
            : `${command.speedKt} knots is below our approach speed of ${envelope.approachIasKt}`,
        );
      }
      if (command.speedKt > envelope.maxIasKt) {
        return no(`we can't do more than ${envelope.maxIasKt} knots`);
      }
      if (command.releaseDistanceNm !== null && ac.approach === null) {
        return no('we are not on an approach, so there is nothing to hold that speed to');
      }
      ac.clearance.speedKt = command.speedKt;
      // A speed given after the approach clearance is the controller taking
      // the spacing back; it holds until the aircraft is released.
      ac.clearance.speedAssignedOnApproach = ac.approach !== null;
      ac.clearance.speedReleaseDistanceNm = command.releaseDistanceNm;

      const restricted =
        !ac.clearance.speedRestrictionCancelled &&
        ac.altitudeFt < SPEED_LIMIT_ALTITUDE_FT &&
        command.speedKt > SPEED_LIMIT_KT;
      const held =
        command.releaseDistanceNm === null
          ? ''
          : ` to ${command.releaseDistanceNm} mile${command.releaseDistanceNm === 1 ? '' : 's'}`;
      const text = `speed ${command.speedKt}${held}`;
      return ok(restricted ? `${text}, we're restricted to ${SPEED_LIMIT_KT} below ten thousand` : text);
    }

    case 'minimumApproachSpeed': {
      if (ac.approach === null) return no('we are not on an approach');
      const speed = ac.profile.speeds.approachIasKt;
      ac.clearance.speedKt = speed;
      ac.clearance.speedAssignedOnApproach = true;
      ac.clearance.speedReleaseDistanceNm = 0;
      return ok(`reducing to our minimum approach speed, ${speed} knots`);
    }

    case 'speedCancel': {
      ac.clearance.speedRestrictionCancelled = true;
      return ok('speed restriction cancelled, resuming normal speed');
    }

    case 'direct': {
      const fix = airspace.fix(command.fix);
      if (fix === undefined) {
        return no(`we don't have ${command.fix} in the database`);
      }
      leaveProcedures(ac);
      // Going direct to a fix that is already on the route cuts the corner:
      // everything before it is dropped and the rest still follows. A fix
      // that is not on the route takes the aircraft off the procedure.
      const index = ac.route.indexOf(fix.name);
      if (index >= 0) {
        ac.route = ac.route.slice(index + 1);
      } else {
        ac.route = [];
        ac.procedure = null;
      }
      ac.clearance.lateralMode = 'direct';
      ac.clearance.directFix = fix.name;
      ac.clearance.turn = 'shortest';
      ac.clearance.turnRemainingDeg = null;
      return ok(`direct ${fix.name}`);
    }

    case 'squawk': {
      if (ac.fuelState === 'emergency') {
        return no(`we are squawking ${ac.squawk} — we have an emergency in progress`);
      }
      ac.squawk = command.code;
      return ok(`squawk ${command.code}`);
    }

    case 'sayFuel':
      return ok(fuelReport(ac));

    case 'approach': {
      const runway = airspace.runway(command.runway);
      if (runway === undefined) {
        return no(`${command.runway} is not a runway here`);
      }
      const approach = airspace.approachForRunway(runway.ident);
      if (approach === undefined) {
        return no(`there is no instrument approach published for runway ${runway.ident}`);
      }
      if (ac.altitudeFt > airspace.sector.ceilingFt) {
        return no('we are far too high to start an approach from here');
      }
      leaveProcedures(ac);
      ac.approach = {
        runway: runway.ident,
        ident: approach.ident,
        localiserCaptured: false,
        glideslopeCaptured: false,
        reportedBlowThrough: false,
        stabilityChecked: false,
      };
      ac.clearance.descendVia = false;
      // The crew manage their own speed from here unless the controller
      // assigns one after this clearance.
      ac.clearance.speedAssignedOnApproach = false;
      ac.clearance.speedReleaseDistanceNm = null;
      return ok(`cleared ILS runway ${runway.ident} approach`);
    }

    case 'cancelApproach': {
      if (ac.approach === null) return no('we are not on an approach');
      const runway = ac.approach.runway;
      ac.approach = null;
      ac.phase = 'cruise';
      ac.clearance.lateralMode = 'heading';
      return ok(`cancelling the approach to runway ${runway}, maintaining present heading`);
    }

    case 'goAround': {
      const report = ctx.goAround(ac, 'on instruction');
      if (report === null) return no('we are not on an approach');
      return ok(report);
    }

    case 'lineUp': {
      if (ac.role !== 'departure' || ac.ground === null) {
        return no('we are already airborne');
      }
      if (ac.ground !== 'queue') return no(`we are already lined up on runway ${ac.departureRunway}`);
      const ident = (command.runway ?? ac.departureRunway ?? ctx.departureRunway).toUpperCase();
      const runway = airspace.runway(ident);
      if (runway === undefined) return no(`${ident} is not a runway here`);
      if (ctx.isRunwayOccupied(runway.ident)) return no(`runway ${runway.ident} is still occupied`);
      ac.ground = 'lineup';
      ac.departureRunway = runway.ident;
      ac.headingDeg = runway.magneticHeadingDeg;
      ac.clearance.headingDeg = runway.magneticHeadingDeg;
      // Sitting on the runway keeps everyone else off it.
      ctx.occupyRunway(runway.ident, 600);
      return ok(`lining up and waiting runway ${runway.ident}`);
    }

    case 'takeoff': {
      if (ac.role !== 'departure' || ac.ground === null) return no('we are already airborne');
      const ident = (ac.departureRunway ?? ctx.departureRunway).toUpperCase();
      const runway = airspace.runway(ident);
      if (runway === undefined) return no(`${ident} is not a runway here`);
      // Lining up first is optional: a clearance to go implies it.
      if (ac.ground === 'queue' && ctx.isRunwayOccupied(runway.ident)) {
        return no(`runway ${runway.ident} is still occupied`);
      }
      ac.ground = 'takeoff';
      ac.departureRunway = runway.ident;
      ac.headingDeg = runway.magneticHeadingDeg;
      ac.clearance.headingDeg = runway.magneticHeadingDeg;
      ctx.occupyRunway(runway.ident, 600);
      return ok(`cleared for takeoff runway ${runway.ident}`);
    }

    case 'descendVia': {
      if (ac.procedure === null) return no('we have no published arrival loaded');
      if (ac.clearance.lateralMode !== 'direct') {
        return no('we are on vectors, we are not on the arrival any more');
      }
      ac.clearance.descendVia = true;
      const leg =
        ac.clearance.directFix === null
          ? undefined
          : airspace.procedureLeg(ac.procedure, ac.clearance.directFix);
      if (leg?.altitudeConstraint != null) ac.clearance.altitudeFt = leg.altitudeConstraint.altitudeFt;
      if (leg?.speedConstraint != null) ac.clearance.speedKt = leg.speedConstraint.speedKt;
      return ok(`descend via the ${ac.procedure} arrival`);
    }

    case 'hold': {
      const fix = airspace.fix(command.fix);
      if (fix === undefined) return no(`we don't have ${command.fix} in the database`);
      const published = airspace.hold(fix.name);
      if (published === undefined) {
        return no(`there is no published hold at ${fix.name}`);
      }
      if (ac.altitudeFt < published.minAltitudeFt - 100) {
        return no(`the hold at ${fix.name} is not published below ${published.minAltitudeFt} feet`);
      }
      leaveProcedures(ac);
      ac.hold = createHoldState(published, command.efcTimeSec);
      ac.clearance.lateralMode = 'hold';
      ac.clearance.directFix = fix.name;
      ac.clearance.turnRemainingDeg = null;
      const efc =
        command.efcTimeSec === null ? '' : `, expect further clearance ${formatHhmm(command.efcTimeSec)}`;
      return ok(`hold at ${fix.name} as published${efc}`);
    }

    case 'contact': {
      ac.handedOff = true;
      ac.handedOffTo = command.facility;
      ac.handedOffFrequencyMhz = command.frequencyMhz;
      const where = command.facility === null ? '' : `${command.facility} on `;
      return ok(`over to ${where}${command.frequencyMhz.toFixed(3).replace(/0+$/, '').replace(/\.$/, '.0')}, good day`);
    }

    default: {
      // Exhaustiveness guard: adding a command without handling it fails here.
      const unreachable: never = command;
      return no(`we didn't copy that (${JSON.stringify(unreachable)})`);
    }
  }
}

function executeAltitude(
  ac: Aircraft,
  command: Extract<Command, { kind: 'altitude' }>,
  airspace: Airspace,
): SingleOutcome {
  const target = command.altitudeFt;

  if (target > airspace.sector.ceilingFt) {
    return no(`${formatFlightLevel(airspace.sector.ceilingFt)} is the top of your airspace`);
  }

  // Outside the published grid there is nothing to check against.
  const msa = airspace.minimumSafeAltitudeFt(ac.position);
  if (msa !== null && target < msa - MSA_BUFFER_FT) {
    return no(`the minimum safe altitude in this area is ${msa} feet`);
  }

  // The sense of the instruction has to match where the aircraft actually is.
  const currentRounded = Math.round(ac.altitudeFt / 100) * 100;
  if (command.sense === 'climb' && target < currentRounded - 100) {
    return no(`we're at ${formatFlightLevel(ac.altitudeFt)}, say again — did you mean descend`);
  }
  if (command.sense === 'descend' && target > currentRounded + 100) {
    return no(`we're at ${formatFlightLevel(ac.altitudeFt)}, say again — did you mean climb`);
  }

  ac.clearance.altitudeFt = target;
  ac.clearance.expedite = command.expedite;
  const verb =
    target > ac.altitudeFt + 100 ? 'climb' : target < ac.altitudeFt - 100 ? 'descend' : 'maintain';
  const spoken =
    target >= airspace.airport.transitionAltitudeFt
      ? `flight level ${formatFlightLevel(target)}`
      : `${target} feet`;
  const prefix = command.expedite ? 'expedite ' : '';
  return ok(verb === 'maintain' ? `${prefix}maintain ${spoken}` : `${prefix}${verb} and maintain ${spoken}`);
}

/**
 * Any instruction that puts the aircraft back on vectors takes it off an
 * approach, out of a hold and off the published descent, exactly as it would
 * in life.
 */
function leaveProcedures(ac: Aircraft): void {
  ac.approach = null;
  ac.hold = null;
  ac.clearance.descendVia = false;
  ac.clearance.speedAssignedOnApproach = false;
  ac.clearance.speedReleaseDistanceNm = null;
  if (ac.phase === 'approach') ac.phase = 'cruise';
}

function ok(text: string): SingleOutcome {
  return { accepted: true, text };
}

function no(text: string): SingleOutcome {
  return { accepted: false, text };
}
