import { describe, expect, it } from 'vitest';
import airspaceData from '../data/airspace.json';
import { Airspace, RawAirspace } from './airspace.js';
import { createHoldState, holdingSpeedKt, outboundCourseTrueDeg, stepHold } from './hold.js';
import { makeTestAircraft } from './testAircraft.js';
import { Aircraft } from './types.js';

const AIRSPACE = new Airspace(airspaceData as unknown as RawAirspace);
const PUBLISHED = AIRSPACE.hold('GUDUR');
if (PUBLISHED === undefined) throw new Error('GUDUR has no published hold');
const HOLD = PUBLISHED;

function makeAircraft(trueTrackDeg: number, type = 'A320'): Aircraft {
  return makeTestAircraft(
    {
      headingDeg: trueTrackDeg,
      trueTrackDeg,
      altitudeFt: 9000,
      iasKt: 250,
      groundspeedKt: 250,
      clearance: {
        headingDeg: trueTrackDeg,
        altitudeFt: 9000,
        speedKt: 250,
        directFix: 'GUDUR',
        lateralMode: 'hold',
      },
    },
    type,
  );
}

describe('the published pattern', () => {
  it('flies outbound on the reciprocal of the inbound course', () => {
    const state = createHoldState(HOLD, null);
    expect(outboundCourseTrueDeg(state)).toBeCloseTo((HOLD.inboundCourseTrueDeg + 180) % 360, 6);
  });

  it('starts by tracking to the fix', () => {
    const state = createHoldState(HOLD, null);
    const steer = stepHold(makeAircraft(0), state, false, 1);
    expect(steer.directToFix).toBe(true);
    expect(state.leg).toBe('toFix');
  });

  it('turns outbound the published way when it reaches the fix', () => {
    const state = createHoldState(HOLD, null);
    const steer = stepHold(makeAircraft(0), state, true, 1);
    expect(state.leg).toBe('outbound');
    expect(state.legTimerSec).toBe(HOLD.legTimeSec);
    expect(steer.turn).toBe(HOLD.turnDirection);
    expect(steer.trackTrueDeg).toBeCloseTo(outboundCourseTrueDeg(state), 6);
  });

  it('runs the outbound leg for the published time and then turns back', () => {
    const state = createHoldState(HOLD, null);
    const ac = makeAircraft(0);
    stepHold(ac, state, true, 1);
    for (let i = 0; i < HOLD.legTimeSec - 1; i++) {
      stepHold(ac, state, false, 1);
      expect(state.leg).toBe('outbound');
    }
    const steer = stepHold(ac, state, false, 2);
    expect(state.leg).toBe('turnInbound');
    expect(steer.turn).toBe(HOLD.turnDirection);
    expect(steer.trackTrueDeg).toBeCloseTo(HOLD.inboundCourseTrueDeg, 6);
  });

  it('goes back to tracking the fix once it is on the inbound course', () => {
    const state = createHoldState(HOLD, null);
    state.leg = 'turnInbound';
    const stillTurning = stepHold(makeAircraft((HOLD.inboundCourseTrueDeg + 90) % 360), state, false, 1);
    expect(state.leg).toBe('turnInbound');
    expect(stillTurning.directToFix).toBe(false);

    const settled = stepHold(makeAircraft(HOLD.inboundCourseTrueDeg), state, false, 1);
    expect(state.leg).toBe('toFix');
    expect(settled.directToFix).toBe(true);
  });

  it('completes a whole circuit and comes back to where it started', () => {
    const state = createHoldState(HOLD, null);
    const ac = makeAircraft(HOLD.inboundCourseTrueDeg);
    stepHold(ac, state, true, 1);
    // Outbound, so the aircraft is flying away from the fix, not towards it.
    ac.trueTrackDeg = outboundCourseTrueDeg(state);
    for (let i = 0; i < HOLD.legTimeSec + 5; i++) stepHold(ac, state, false, 1);
    expect(state.leg).toBe('turnInbound');
    ac.trueTrackDeg = HOLD.inboundCourseTrueDeg;
    stepHold(ac, state, false, 1);
    expect(state.leg).toBe('toFix');
    stepHold(ac, state, true, 1);
    expect(state.leg).toBe('outbound');
  });
});

describe('holding speed', () => {
  it('never exceeds the published maximum', () => {
    const ac = makeAircraft(0);
    expect(holdingSpeedKt(ac, HOLD.maxSpeedKt)).toBe(HOLD.maxSpeedKt);
  });

  it('keeps a slower assigned speed', () => {
    const ac = makeAircraft(0);
    ac.clearance.speedKt = 200;
    expect(holdingSpeedKt(ac, HOLD.maxSpeedKt)).toBe(200);
  });

  it('respects a type that cannot reach the published maximum', () => {
    const cessna = makeAircraft(0, 'C172');
    expect(holdingSpeedKt(cessna, HOLD.maxSpeedKt)).toBe(cessna.profile.speeds.maxIasKt);
  });
});

describe('entry is reported once', () => {
  it('starts unestablished', () => {
    expect(createHoldState(HOLD, null).established).toBe(false);
  });
});

describe('expect further clearance', () => {
  it('is carried on the hold state', () => {
    const state = createHoldState(HOLD, 14 * 3600 + 20 * 60);
    expect(state.efcTimeSec).toBe(51600);
    expect(createHoldState(HOLD, null).efcTimeSec).toBeNull();
  });
});
