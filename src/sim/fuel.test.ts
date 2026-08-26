import { describe, expect, it } from 'vitest';
import {
  EMERGENCY_FUEL_MINUTES,
  EMERGENCY_SQUAWK,
  MINIMUM_FUEL_MINUTES,
  enduranceMinutes,
  fuelReport,
  stateForEndurance,
  updateFuel,
} from './fuel.js';
import { fuelBurnKgPerSec } from './performance.js';
import { TEST_CATALOGUE as CATALOGUE, makeTestAircraft } from './testAircraft.js';
import { Aircraft } from './types.js';

const FIELD_ELEVATION_FT = 777;

function makeAircraft(fuelKg: number, type = 'A320'): Aircraft {
  return makeTestAircraft(
    {
      altitudeFt: 8000,
      iasKt: 250,
      groundspeedKt: 250,
      fuelKg,
      clearance: { altitudeFt: 8000, speedKt: 250 },
    },
    type,
  );
}

/** Fuel for exactly `minutes` of cruise. */
function fuelForMinutes(minutes: number, type = 'A320'): number {
  return fuelBurnKgPerSec(CATALOGUE.require(type), 'cruise') * minutes * 60;
}

describe('endurance', () => {
  it('is fuel divided by the burn rate for the phase', () => {
    const ac = makeAircraft(fuelForMinutes(45));
    expect(enduranceMinutes(ac)).toBeCloseTo(45, 6);
  });

  it('shortens in the climb and lengthens in the descent', () => {
    const ac = makeAircraft(fuelForMinutes(45));
    const cruise = enduranceMinutes(ac);
    ac.phase = 'climb';
    expect(enduranceMinutes(ac)).toBeLessThan(cruise);
    ac.phase = 'descent';
    expect(enduranceMinutes(ac)).toBeGreaterThan(cruise);
  });
});

describe('state thresholds', () => {
  it('reads across from endurance', () => {
    expect(stateForEndurance(90)).toBe('normal');
    expect(stateForEndurance(MINIMUM_FUEL_MINUTES)).toBe('minimum');
    expect(stateForEndurance(20)).toBe('minimum');
    expect(stateForEndurance(EMERGENCY_FUEL_MINUTES)).toBe('emergency');
    expect(stateForEndurance(3)).toBe('emergency');
  });
});

describe('burning fuel', () => {
  it('takes fuel out of the tanks and mass off the aeroplane', () => {
    const ac = makeAircraft(4000);
    const before = ac.massKg;
    updateFuel(ac, 600, FIELD_ELEVATION_FT);
    const burnt = 4000 - ac.fuelKg;
    expect(burnt).toBeGreaterThan(0);
    expect(before - ac.massKg).toBeCloseTo(burnt, 9);
  });

  it('says nothing at all while there is plenty', () => {
    const ac = makeAircraft(fuelForMinutes(120));
    expect(updateFuel(ac, 60, FIELD_ELEVATION_FT)).toEqual([]);
    expect(ac.fuelState).toBe('normal');
  });

  it('advises minimum fuel once under thirty minutes', () => {
    const ac = makeAircraft(fuelForMinutes(MINIMUM_FUEL_MINUTES + 0.5));
    const calls = updateFuel(ac, 60, FIELD_ELEVATION_FT);
    expect(ac.fuelState).toBe('minimum');
    expect(calls.join(' ')).toMatch(/minimum fuel/);
    expect(calls.join(' ')).toMatch(/no undue delay/);
  });

  it('only advises once, not on every step', () => {
    const ac = makeAircraft(fuelForMinutes(MINIMUM_FUEL_MINUTES + 0.5));
    expect(updateFuel(ac, 60, FIELD_ELEVATION_FT)).toHaveLength(1);
    expect(updateFuel(ac, 60, FIELD_ELEVATION_FT)).toEqual([]);
  });

  it('declares an emergency and squawks 7700 under fifteen minutes', () => {
    const ac = makeAircraft(fuelForMinutes(EMERGENCY_FUEL_MINUTES + 0.5));
    const calls = updateFuel(ac, 60, FIELD_ELEVATION_FT);
    expect(ac.fuelState).toBe('emergency');
    expect(ac.squawk).toBe(EMERGENCY_SQUAWK);
    expect(calls.join(' ')).toMatch(/MAYDAY MAYDAY MAYDAY/);
    expect(calls.join(' ')).toMatch(/request priority/);
  });

  it('escalates straight to an emergency if that is where it starts', () => {
    const ac = makeAircraft(fuelForMinutes(4));
    updateFuel(ac, 1, FIELD_ELEVATION_FT);
    expect(ac.fuelState).toBe('emergency');
  });

  it('never quietly recovers once it has declared', () => {
    const ac = makeAircraft(fuelForMinutes(EMERGENCY_FUEL_MINUTES - 1));
    updateFuel(ac, 1, FIELD_ELEVATION_FT);
    expect(ac.fuelState).toBe('emergency');
    ac.fuelKg = fuelForMinutes(200);
    updateFuel(ac, 1, FIELD_ELEVATION_FT);
    expect(ac.fuelState).toBe('emergency');
  });

  it('cannot burn past empty, and starts down when the tanks are dry', () => {
    const ac = makeAircraft(fuelForMinutes(0.2));
    const calls: string[] = [];
    for (let i = 0; i < 60; i++) calls.push(...updateFuel(ac, 1, FIELD_ELEVATION_FT));
    expect(ac.fuelKg).toBe(0);
    expect(calls.join(' ')).toMatch(/flamed out/);
    expect(ac.clearance.altitudeFt).toBe(FIELD_ELEVATION_FT);
  });
});

describe('say fuel remaining', () => {
  it('answers in kilos and minutes', () => {
    const ac = makeAircraft(fuelForMinutes(50));
    const report = fuelReport(ac);
    expect(report).toMatch(/kilos remaining/);
    expect(report).toMatch(/about 50 minutes/);
  });
});
