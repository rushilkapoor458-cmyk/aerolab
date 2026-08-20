import { describe, expect, it } from 'vitest';
import { angleDiff, normalizeDeg } from './geo.js';
import {
  GENERIC,
  MAX_BANK_DEG,
  Wind,
  bankForTurnRate,
  commandedBankDeg,
  effectiveTargetSpeedKt,
  headingForTrack,
  rollOutAnticipationDeg,
  signedTurn,
  stepAircraft,
  turnRadiusNm,
  turnRateForBank,
  windTriangle,
} from './flight.js';
import { Aircraft } from './types.js';

const CALM: Wind = { fromTrueDeg: 0, speedKt: 0 };

function makeAircraft(overrides: Partial<Aircraft> = {}): Aircraft {
  const base: Aircraft = {
    id: 'ac1',
    callsign: 'AIC101',
    type: 'A320',
    wake: 'M',
    role: 'arrival',
    position: { x: 0, y: 0 },
    altitudeFt: 6000,
    headingDeg: 90,
    trueTrackDeg: 90,
    iasKt: 220,
    groundspeedKt: 220,
    bankDeg: 0,
    verticalSpeedFpm: 0,
    squawk: '4271',
    clearance: {
      headingDeg: 90,
      turn: 'shortest',
      turnRemainingDeg: null,
      altitudeFt: 6000,
      speedKt: 220,
      directFix: null,
      lateralMode: 'heading',
      speedRestrictionCancelled: false,
      expedite: false,
    },
    route: [],
    phase: 'cruise',
    history: [],
    sweepTimerSec: 4,
    handedOff: false,
  };
  return { ...base, ...overrides };
}

/** Fly the aircraft until it settles, returning the track it flew. */
function fly(ac: Aircraft, targetHeading: number | null, seconds: number, wind: Wind = CALM): void {
  const steps = Math.round(seconds / 0.25);
  for (let i = 0; i < steps; i++) {
    stepAircraft(ac, targetHeading, 0.25, { wind, magneticVariationDeg: 0 });
  }
}

describe('turn geometry', () => {
  it('uses standard rate when the bank needed stays under the limit', () => {
    // At 140 kt true a three degree per second turn needs about 21 degrees.
    expect(bankForTurnRate(3, 140)).toBeCloseTo(21.06, 1);
    expect(commandedBankDeg(140)).toBeCloseTo(21.06, 1);
  });

  it('caps the bank at 25 degrees, so fast aircraft turn slower than standard rate', () => {
    expect(commandedBankDeg(300)).toBe(MAX_BANK_DEG);
    expect(turnRateForBank(MAX_BANK_DEG, 300)).toBeLessThan(3);
    expect(turnRateForBank(MAX_BANK_DEG, 300)).toBeCloseTo(1.696, 2);
  });

  it('bank and turn rate are inverses of each other', () => {
    const rate = turnRateForBank(18, 210);
    expect(bankForTurnRate(rate, 210)).toBeCloseTo(18, 9);
  });

  it('turn radius grows with the square of the speed', () => {
    const slow = turnRadiusNm(MAX_BANK_DEG, 150);
    const fast = turnRadiusNm(MAX_BANK_DEG, 300);
    expect(fast / slow).toBeCloseTo(4, 1);
  });

  it('anticipates the roll out by half the turn rate times the roll out time', () => {
    // 25 degrees of bank at 250 kt: 2.03 deg/s, rolling out over 8.3 s.
    const anticipation = rollOutAnticipationDeg(25, 250);
    expect(anticipation).toBeCloseTo((turnRateForBank(25, 250) / 2) * (25 / 3), 6);
    expect(anticipation).toBeGreaterThan(5);
  });
});

describe('signedTurn', () => {
  it('takes the short way when no direction is named', () => {
    expect(signedTurn(350, 10, 'shortest')).toBe(20);
    expect(signedTurn(10, 350, 'shortest')).toBe(-20);
  });

  it('takes the long way round when the controller names the side', () => {
    expect(signedTurn(350, 10, 'left')).toBe(-340);
    expect(signedTurn(10, 350, 'right')).toBe(340);
  });

  it('agrees with the short way when the named side is the short one', () => {
    expect(signedTurn(90, 180, 'right')).toBe(90);
    expect(signedTurn(180, 90, 'left')).toBe(-90);
  });
});

describe('flying a turn', () => {
  it('rolls in, turns, and settles on the heading without overshooting', () => {
    const ac = makeAircraft({ headingDeg: 90, iasKt: 220 });
    ac.clearance.headingDeg = 180;
    fly(ac, 180, 120);
    expect(ac.headingDeg).toBeCloseTo(180, 1);
    expect(ac.bankDeg).toBeCloseTo(0, 3);
  });

  it('never banks past the limit on the way round', () => {
    const ac = makeAircraft({ headingDeg: 0, iasKt: 280 });
    let worst = 0;
    for (let i = 0; i < 400; i++) {
      stepAircraft(ac, 200, 0.25, { wind: CALM, magneticVariationDeg: 0 });
      worst = Math.max(worst, Math.abs(ac.bankDeg));
    }
    expect(worst).toBeLessThanOrEqual(MAX_BANK_DEG + 1e-9);
    expect(ac.headingDeg).toBeCloseTo(200, 1);
  });

  it('turns the long way when told to turn left through north', () => {
    const ac = makeAircraft({ headingDeg: 10, iasKt: 200 });
    ac.clearance.turn = 'left';
    ac.clearance.turnRemainingDeg = signedTurn(10, 30, 'left');
    let sawWest = false;
    for (let i = 0; i < 1200; i++) {
      stepAircraft(ac, 30, 0.25, { wind: CALM, magneticVariationDeg: 0 });
      if (Math.abs(angleDiff(ac.headingDeg, 270)) < 15) sawWest = true;
    }
    expect(sawWest).toBe(true);
    expect(ac.headingDeg).toBeCloseTo(30, 1);
  });
});

describe('wind triangle', () => {
  it('a pure headwind only slows the groundspeed', () => {
    const result = windTriangle(0, 200, { fromTrueDeg: 0, speedKt: 30 });
    expect(result.groundspeedKt).toBeCloseTo(170, 6);
    expect(result.trackTrueDeg).toBeCloseTo(0, 6);
  });

  it('a pure tailwind only raises the groundspeed', () => {
    const result = windTriangle(0, 200, { fromTrueDeg: 180, speedKt: 30 });
    expect(result.groundspeedKt).toBeCloseTo(230, 6);
  });

  it('a crosswind pushes the track downwind of the heading', () => {
    const result = windTriangle(0, 100, { fromTrueDeg: 90, speedKt: 20 });
    expect(result.trackTrueDeg).toBeCloseTo(348.69, 2);
    expect(result.groundspeedKt).toBeCloseTo(101.98, 2);
  });

  it('crabbing into wind makes good the desired track', () => {
    const wind: Wind = { fromTrueDeg: 90, speedKt: 20 };
    const heading = headingForTrack(0, 100, wind);
    expect(heading).not.toBeNull();
    expect(heading).toBeCloseTo(11.54, 2);
    const flown = windTriangle(heading ?? 0, 100, wind);
    expect(angleDiff(flown.trackTrueDeg, 0)).toBeCloseTo(0, 6);
  });

  it('gives up when the wind is stronger than the aircraft', () => {
    expect(headingForTrack(0, 30, { fromTrueDeg: 90, speedKt: 60 })).toBeNull();
  });

  it('drifts an aircraft off its assigned heading, which is why vectors need allowance', () => {
    const ac = makeAircraft({ headingDeg: 0, iasKt: 200, altitudeFt: 0 });
    ac.clearance.headingDeg = 0;
    ac.clearance.altitudeFt = 0;
    fly(ac, 0, 60, { fromTrueDeg: 270, speedKt: 40 });
    expect(ac.headingDeg).toBeCloseTo(0, 6);
    expect(ac.trueTrackDeg).toBeGreaterThan(5); // Blown east of the heading.
    expect(ac.position.x).toBeGreaterThan(0);
  });
});

describe('vertical and speed behaviour', () => {
  it('captures a cleared level from below without busting it', () => {
    const ac = makeAircraft({ altitudeFt: 6000 });
    ac.clearance.altitudeFt = 9000;
    let highest = 0;
    for (let i = 0; i < 2000; i++) {
      stepAircraft(ac, null, 0.25, { wind: CALM, magneticVariationDeg: 0 });
      highest = Math.max(highest, ac.altitudeFt);
    }
    expect(ac.altitudeFt).toBe(9000);
    expect(highest).toBeLessThanOrEqual(9000 + 1e-6);
  });

  it('climbs no faster than the profile allows', () => {
    const ac = makeAircraft({ altitudeFt: 3000 });
    ac.clearance.altitudeFt = 15000;
    fly(ac, null, 60);
    expect(ac.verticalSpeedFpm).toBeCloseTo(GENERIC.climbRateFpm, 6);
  });

  it('expedite uses the higher rate', () => {
    const ac = makeAircraft({ altitudeFt: 3000 });
    ac.clearance.altitudeFt = 15000;
    ac.clearance.expedite = true;
    fly(ac, null, 60);
    expect(ac.verticalSpeedFpm).toBeCloseTo(GENERIC.expediteClimbRateFpm, 6);
  });

  it('holds 250 knots below ten thousand feet until the restriction is cancelled', () => {
    const ac = makeAircraft({ altitudeFt: 8000, iasKt: 250 });
    ac.clearance.speedKt = 300;
    expect(effectiveTargetSpeedKt(ac)).toBe(250);
    ac.clearance.speedRestrictionCancelled = true;
    expect(effectiveTargetSpeedKt(ac)).toBe(300);
  });

  it('lets the same aircraft do 300 knots above ten thousand', () => {
    const ac = makeAircraft({ altitudeFt: 12000, iasKt: 250 });
    ac.clearance.speedKt = 300;
    expect(effectiveTargetSpeedKt(ac)).toBe(300);
  });

  it('slows more sluggishly in the descent than in the level', () => {
    const descending = makeAircraft({ altitudeFt: 10000, iasKt: 280 });
    descending.clearance.altitudeFt = 4000;
    descending.clearance.speedKt = 210;
    descending.clearance.speedRestrictionCancelled = true;

    const level = makeAircraft({ altitudeFt: 10000, iasKt: 280 });
    level.clearance.altitudeFt = 10000;
    level.clearance.speedKt = 210;
    level.clearance.speedRestrictionCancelled = true;

    fly(descending, null, 30);
    fly(level, null, 30);
    expect(descending.iasKt).toBeGreaterThan(level.iasKt);
  });
});

describe('position integration', () => {
  it('covers groundspeed times time along the track', () => {
    const ac = makeAircraft({ headingDeg: 90, iasKt: 180, altitudeFt: 0 });
    ac.clearance.speedKt = 180;
    ac.clearance.altitudeFt = 0; // Level, so true airspeed does not creep up.
    fly(ac, 90, 60);
    // 180 kt for one minute is three nautical miles, due east.
    expect(ac.position.x).toBeCloseTo(3, 2);
    expect(ac.position.y).toBeCloseTo(0, 6);
    expect(normalizeDeg(ac.trueTrackDeg)).toBeCloseTo(90, 6);
  });

  it('lays down one history dot per radar sweep and keeps the last five', () => {
    const ac = makeAircraft();
    fly(ac, 90, 120);
    expect(ac.history).toHaveLength(5);
  });
});
