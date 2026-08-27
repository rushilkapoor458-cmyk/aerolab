/**
 * Holding patterns.
 *
 * A racetrack flown as three legs: track to the fix, turn onto the outbound
 * heading and run the leg time, then turn back onto the inbound course and
 * track to the fix again.
 *
 * Entry is simplified to a direct entry — the parallel and teardrop entries
 * are not modelled — which is noted in the README.
 */

import { Hold } from './airspace.js';
import { angleDiff, normalizeDeg } from './geo.js';
import { Aircraft, HoldState } from './types.js';

/** How close the aircraft has to be to the inbound course to start tracking. */
const INBOUND_TOLERANCE_DEG = 12;

export function createHoldState(hold: Hold, efcTimeSec: number | null): HoldState {
  return {
    fix: hold.fix,
    inboundCourseTrueDeg: hold.inboundCourseTrueDeg,
    turnDirection: hold.turnDirection,
    legTimeSec: hold.legTimeSec,
    leg: 'toFix',
    legTimerSec: 0,
    established: false,
    efcTimeSec,
  };
}

/** The heading to fly outbound: the reciprocal of the inbound course. */
export function outboundCourseTrueDeg(state: HoldState): number {
  return normalizeDeg(state.inboundCourseTrueDeg + 180);
}

export interface HoldSteer {
  /** Track the aircraft should make good, true degrees, or null to go direct. */
  readonly trackTrueDeg: number | null;
  /** True while the aircraft should steer straight at the holding fix. */
  readonly directToFix: boolean;
  /** Turn direction to use, so the pattern turns the published way. */
  readonly turn: 'left' | 'right' | 'shortest';
}

/**
 * Advance the pattern by `dtSec` and say how to steer. `atFix` is true on the
 * step the aircraft passes overhead.
 */
export function stepHold(
  ac: Aircraft,
  state: HoldState,
  atFix: boolean,
  dtSec: number,
): HoldSteer {
  switch (state.leg) {
    case 'toFix': {
      if (atFix) {
        state.leg = 'outbound';
        state.legTimerSec = state.legTimeSec;
        return {
          trackTrueDeg: outboundCourseTrueDeg(state),
          directToFix: false,
          turn: state.turnDirection,
        };
      }
      return { trackTrueDeg: null, directToFix: true, turn: 'shortest' };
    }

    case 'outbound': {
      state.legTimerSec -= dtSec;
      if (state.legTimerSec <= 0) {
        state.leg = 'turnInbound';
        return {
          trackTrueDeg: state.inboundCourseTrueDeg,
          directToFix: false,
          turn: state.turnDirection,
        };
      }
      return {
        trackTrueDeg: outboundCourseTrueDeg(state),
        directToFix: false,
        turn: 'shortest',
      };
    }

    case 'turnInbound': {
      const offCourse = Math.abs(angleDiff(ac.trueTrackDeg, state.inboundCourseTrueDeg));
      if (offCourse <= INBOUND_TOLERANCE_DEG) {
        state.leg = 'toFix';
        return { trackTrueDeg: null, directToFix: true, turn: 'shortest' };
      }
      return {
        trackTrueDeg: state.inboundCourseTrueDeg,
        directToFix: false,
        turn: state.turnDirection,
      };
    }

    default: {
      const unreachable: never = state.leg;
      throw new Error(`unknown holding leg ${String(unreachable)}`);
    }
  }
}

/** Speed to fly in the pattern: never faster than the published maximum. */
export function holdingSpeedKt(ac: Aircraft, maxSpeedKt: number): number {
  return Math.min(ac.clearance.speedKt, maxSpeedKt, ac.profile.speeds.maxIasKt);
}
