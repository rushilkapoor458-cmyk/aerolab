import { describe, expect, it } from 'vitest';
import aircraftData from '../data/aircraft.json';
import { angleDiff, normalizeDeg } from './geo.js';
import {
  MAX_BANK_DEG,
  StepContext,
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
import { PerformanceCatalogue, RawPerformance } from './performance.js';
import { Aircraft } from './types.js';

const CATALOGUE = new PerformanceCatalogue(aircraftData as unknown as RawPerformance);
const CALM: Wind = { fromTrueDeg: 0, speedKt: 0 };

function context(wind: Wind = CALM): StepContext {
  return { windAt: () => wind, magneticVariationDeg: 0 };
}

function makeAircraft(overrides: Partial<Aircraft> = {}, type = 'A320'): Aircraft {
  const profile = CATALOGUE.require(type);
  const base: Aircraft = {
    id: 'ac1',
    callsign: 'AIC101',
    type: profile.icao,
    profile,
    wake: profile.wake,
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
    massKg: profile.mass.referenceKg,
    fuelKg: profile.typicalArrivalFuelKg,
    fuelState: 'normal',
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
    handedOffTo: null,
    handedOffFrequencyMhz: null,
  };
  return { ...base, ...overrides };
}

/** Fly the aircraft for a while at the simulation's own substep. */
function fly(ac: Aircraft, targetHeading: number | null, seconds: number, wind: Wind = CALM): void {
  const ctx = context(wind);
  const steps = Math.round(seconds / 0.25);
  for (let i = 0; i < steps; i++) stepAircraft(ac, targetHeading, 0.25, ctx);
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
    const ctx = context();
    let worst = 0;
    for (let i = 0; i < 400; i++) {
      stepAircraft(ac, 200, 0.25, ctx);
      worst = Math.max(worst, Math.abs(ac.bankDeg));
    }
    expect(worst).toBeLessThanOrEqual(MAX_BANK_DEG + 1e-9);
    expect(ac.headingDeg).toBeCloseTo(200, 1);
  });

  it('turns the long way when told to turn left through north', () => {
    const ac = makeAircraft({ headingDeg: 10, iasKt: 220 });
    ac.clearance.turn = 'left';
    ac.clearance.turnRemainingDeg = signedTurn(10, 30, 'left');
    const ctx = context();
    let sawWest = false;
    for (let i = 0; i < 1200; i++) {
      stepAircraft(ac, 30, 0.25, ctx);
      if (Math.abs(angleDiff(ac.headingDeg, 270)) < 15) sawWest = true;
    }
    expect(sawWest).toBe(true);
    expect(ac.headingDeg).toBeCloseTo(30, 1);
  });

  it('a heavy turns through a bigger radius than a light aircraft at the same bank', () => {
    // Not a mass effect: the 777 simply flies faster, and radius follows speed.
    const heavy = turnRadiusNm(MAX_BANK_DEG, 300);
    const light = turnRadiusNm(MAX_BANK_DEG, 110);
    expect(heavy).toBeGreaterThan(light * 5);
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
    const ac = makeAircraft({ headingDeg: 0, iasKt: 220, altitudeFt: 0 });
    ac.clearance.headingDeg = 0;
    ac.clearance.altitudeFt = 0;
    fly(ac, 0, 60, { fromTrueDeg: 270, speedKt: 40 });
    expect(ac.headingDeg).toBeCloseTo(0, 6);
    expect(ac.trueTrackDeg).toBeGreaterThan(5); // Blown east of the heading.
    expect(ac.position.x).toBeGreaterThan(0);
  });

  it('uses the wind at the aircraft, not one wind for the whole sector', () => {
    // A stiff wind above 10,000 ft and calm below it.
    const ctx: StepContext = {
      windAt: (altitudeFt) =>
        altitudeFt > 10000 ? { fromTrueDeg: 270, speedKt: 60 } : { fromTrueDeg: 270, speedKt: 0 },
      magneticVariationDeg: 0,
    };
    const high = makeAircraft({ altitudeFt: 14000, headingDeg: 0, iasKt: 250 });
    high.clearance.altitudeFt = 14000;
    const low = makeAircraft({ altitudeFt: 4000, headingDeg: 0, iasKt: 250 });
    low.clearance.altitudeFt = 4000;
    for (let i = 0; i < 240; i++) {
      stepAircraft(high, 0, 0.25, ctx);
      stepAircraft(low, 0, 0.25, ctx);
    }
    expect(high.position.x).toBeGreaterThan(0.8);
    expect(low.position.x).toBeCloseTo(0, 6);
  });
});

describe('vertical performance', () => {
  it('captures a cleared level from below without busting it', () => {
    const ac = makeAircraft({ altitudeFt: 6000 });
    ac.clearance.altitudeFt = 9000;
    const ctx = context();
    let highest = 0;
    for (let i = 0; i < 2000; i++) {
      stepAircraft(ac, null, 0.25, ctx);
      highest = Math.max(highest, ac.altitudeFt);
    }
    expect(ac.altitudeFt).toBe(9000);
    expect(highest).toBeLessThanOrEqual(9000 + 1e-6);
  });

  it('climbs more slowly the higher it gets', () => {
    const ac = makeAircraft({ altitudeFt: 1000 });
    ac.clearance.altitudeFt = 15000;
    fly(ac, null, 40);
    const low = ac.verticalSpeedFpm;
    while (ac.altitudeFt < 12000) fly(ac, null, 10);
    const high = ac.verticalSpeedFpm;
    expect(low).toBeGreaterThan(2000);
    expect(high).toBeLessThan(low - 300);
  });

  it('climbs more slowly when it is heavy', () => {
    const light = makeAircraft({ altitudeFt: 3000, massKg: 52000 });
    const heavy = makeAircraft({ altitudeFt: 3000, massKg: 75000 });
    light.clearance.altitudeFt = 15000;
    heavy.clearance.altitudeFt = 15000;
    fly(light, null, 40);
    fly(heavy, null, 40);
    expect(light.verticalSpeedFpm).toBeGreaterThan(heavy.verticalSpeedFpm + 300);
  });

  it('a Cessna and a 777 do not climb at the same rate', () => {
    const cessna = makeAircraft({ altitudeFt: 2000, iasKt: 100 }, 'C172');
    const boeing = makeAircraft({ altitudeFt: 2000, iasKt: 250 }, 'B77W');
    cessna.clearance.altitudeFt = 10000;
    cessna.clearance.speedKt = 100;
    boeing.clearance.altitudeFt = 10000;
    boeing.clearance.speedKt = 250;
    fly(cessna, null, 40);
    fly(boeing, null, 40);
    expect(cessna.verticalSpeedFpm).toBeLessThan(900);
    expect(boeing.verticalSpeedFpm).toBeGreaterThan(1500);
  });

  it('expedite uses the profile factor', () => {
    const normal = makeAircraft({ altitudeFt: 3000 });
    const quick = makeAircraft({ altitudeFt: 3000 });
    normal.clearance.altitudeFt = 15000;
    quick.clearance.altitudeFt = 15000;
    quick.clearance.expedite = true;
    fly(normal, null, 30);
    fly(quick, null, 30);
    expect(quick.verticalSpeedFpm / normal.verticalSpeedFpm).toBeCloseTo(
      normal.profile.expediteFactor,
      1,
    );
  });

  it('cannot go down and slow down at the same time', () => {
    const justDescending = makeAircraft({ altitudeFt: 12000, iasKt: 280 });
    justDescending.clearance.altitudeFt = 5000;
    justDescending.clearance.speedKt = 280;
    justDescending.clearance.speedRestrictionCancelled = true;

    const both = makeAircraft({ altitudeFt: 12000, iasKt: 280 });
    both.clearance.altitudeFt = 5000;
    both.clearance.speedKt = 210;
    both.clearance.speedRestrictionCancelled = true;

    fly(justDescending, null, 20);
    fly(both, null, 20);
    expect(Math.abs(both.verticalSpeedFpm)).toBeLessThan(Math.abs(justDescending.verticalSpeedFpm));
  });
});

describe('speed behaviour', () => {
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

  it('clamps a request to the type envelope', () => {
    const dash = makeAircraft({ altitudeFt: 12000, iasKt: 250 }, 'Q400');
    dash.clearance.speedKt = 400;
    expect(effectiveTargetSpeedKt(dash)).toBe(dash.profile.speeds.maxIasKt);
    dash.clearance.speedKt = 90;
    expect(effectiveTargetSpeedKt(dash)).toBe(dash.profile.speeds.minCleanIasKt);
  });

  it('slows more sluggishly in the descent than in the level', () => {
    const descending = makeAircraft({ altitudeFt: 12000, iasKt: 280 });
    descending.clearance.altitudeFt = 4000;
    descending.clearance.speedKt = 210;
    descending.clearance.speedRestrictionCancelled = true;

    const level = makeAircraft({ altitudeFt: 12000, iasKt: 280 });
    level.clearance.altitudeFt = 12000;
    level.clearance.speedKt = 210;
    level.clearance.speedRestrictionCancelled = true;

    fly(descending, null, 30);
    fly(level, null, 30);
    expect(descending.iasKt).toBeGreaterThan(level.iasKt);
  });

  it('accelerates less readily in a steep turn', () => {
    const straight = makeAircraft({ altitudeFt: 12000, iasKt: 240 });
    straight.clearance.speedKt = 300;
    straight.clearance.speedRestrictionCancelled = true;

    const turning = makeAircraft({ altitudeFt: 12000, iasKt: 240, headingDeg: 90 });
    turning.clearance.speedKt = 300;
    turning.clearance.speedRestrictionCancelled = true;

    fly(straight, 90, 40);
    fly(turning, 270, 40);
    expect(Math.abs(turning.bankDeg)).toBeGreaterThan(15);
    expect(turning.iasKt).toBeLessThan(straight.iasKt);
  });
});

describe('position integration', () => {
  it('covers groundspeed times time along the track', () => {
    const ac = makeAircraft({ headingDeg: 90, iasKt: 220, altitudeFt: 0 });
    ac.clearance.speedKt = 220;
    ac.clearance.altitudeFt = 0; // Level, so true airspeed does not creep up.
    fly(ac, 90, 60);
    expect(ac.position.x).toBeCloseTo(220 / 60, 2);
    expect(ac.position.y).toBeCloseTo(0, 6);
    expect(normalizeDeg(ac.trueTrackDeg)).toBeCloseTo(90, 6);
  });

  it('lays down one history dot per radar sweep and keeps the last five', () => {
    const ac = makeAircraft();
    fly(ac, 90, 120);
    expect(ac.history).toHaveLength(5);
  });
});
