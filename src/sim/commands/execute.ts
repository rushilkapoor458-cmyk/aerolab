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
import { SPEED_LIMIT_ALTITUDE_FT, SPEED_LIMIT_KT, signedTurn } from '../flight.js';
import { fuelReport } from '../fuel.js';
import { Aircraft } from '../types.js';
import { formatFlightLevel } from '../units.js';
import { Command } from './types.js';

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
  airspace: Airspace,
): ExecutionOutcome {
  const accepted: string[] = [];
  const refused: string[] = [];

  for (const command of commands) {
    const outcome = executeOne(ac, command, airspace);
    if (outcome.accepted) accepted.push(outcome.text);
    else refused.push(outcome.text);
  }

  const parts: string[] = [];
  if (accepted.length > 0) parts.push(accepted.join(', '));
  for (const reason of refused) parts.push(`unable, ${reason}`);
  return { readback: `${parts.join(', ')}, ${ac.callsign}`, rejected: refused.length > 0 };
}

function executeOne(ac: Aircraft, command: Command, airspace: Airspace): SingleOutcome {
  switch (command.kind) {
    case 'heading': {
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
      if (command.speedKt < envelope.minCleanIasKt) {
        return no(
          `${command.speedKt} knots is below our minimum clean speed of ${envelope.minCleanIasKt}`,
        );
      }
      if (command.speedKt > envelope.maxIasKt) {
        return no(`we can't do more than ${envelope.maxIasKt} knots`);
      }
      ac.clearance.speedKt = command.speedKt;
      const restricted =
        !ac.clearance.speedRestrictionCancelled &&
        ac.altitudeFt < SPEED_LIMIT_ALTITUDE_FT &&
        command.speedKt > SPEED_LIMIT_KT;
      const text = `speed ${command.speedKt}`;
      return ok(restricted ? `${text}, we're restricted to ${SPEED_LIMIT_KT} below ten thousand` : text);
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

  const msa = airspace.minimumSafeAltitudeFt(ac.position);
  if (target < msa - MSA_BUFFER_FT) {
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

function ok(text: string): SingleOutcome {
  return { accepted: true, text };
}

function no(text: string): SingleOutcome {
  return { accepted: false, text };
}
