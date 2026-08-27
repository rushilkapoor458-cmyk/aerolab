import { describe, expect, it } from 'vitest';
import aircraftData from '../data/aircraft.json';
import {
  PerformanceCatalogue,
  RawPerformance,
  accelerationKtPerSec,
  climbRateFpm,
  descentRateFpm,
  fuelBurnKgPerSec,
  interpolateRate,
  massFactor,
} from './performance.js';

const CATALOGUE = new PerformanceCatalogue(aircraftData as unknown as RawPerformance);

describe('the catalogue', () => {
  it('holds every type the brief asked for', () => {
    expect(CATALOGUE.icaoCodes()).toEqual(['A320', 'A359', 'ATR72', 'B738', 'B77W', 'C172', 'Q400']);
  });

  it('is case insensitive and fails loudly on an unknown type', () => {
    expect(CATALOGUE.get('a320')?.icao).toBe('A320');
    expect(() => CATALOGUE.require('B744')).toThrow(/no performance profile for B744/);
  });

  it('gives every type a wake category and a sane envelope', () => {
    for (const profile of CATALOGUE.all()) {
      expect(['L', 'M', 'H', 'J']).toContain(profile.wake);
      expect(profile.speeds.minCleanIasKt).toBeLessThan(profile.speeds.maxIasKt);
      expect(profile.speeds.approachIasKt).toBeLessThanOrEqual(profile.speeds.minCleanIasKt);
      expect(profile.mass.minimumKg).toBeLessThan(profile.mass.referenceKg);
      expect(profile.mass.referenceKg).toBeLessThan(profile.mass.maximumKg);
      expect(profile.fuelCapacityKg).toBeGreaterThan(profile.typicalArrivalFuelKg);
    }
  });

  it('rejects a rate table that is out of order', () => {
    const broken: RawPerformance = {
      schemaVersion: 1,
      types: [
        {
          ...CATALOGUE.require('A320'),
          climbRateFpm: [
            { altitudeFt: 10000, rateFpm: 1000 },
            { altitudeFt: 0, rateFpm: 2000 },
          ],
        },
      ],
    };
    expect(() => new PerformanceCatalogue(broken)).toThrow(/ascending altitude order/);
  });
});

describe('rate interpolation', () => {
  const table = [
    { altitudeFt: 0, rateFpm: 2000 },
    { altitudeFt: 10000, rateFpm: 1000 },
  ];

  it('hits the tabulated points exactly', () => {
    expect(interpolateRate(table, 0)).toBe(2000);
    expect(interpolateRate(table, 10000)).toBe(1000);
  });

  it('interpolates in between', () => {
    expect(interpolateRate(table, 5000)).toBe(1500);
    expect(interpolateRate(table, 2500)).toBe(1750);
  });

  it('holds flat outside the table rather than extrapolating to nonsense', () => {
    expect(interpolateRate(table, -3000)).toBe(2000);
    expect(interpolateRate(table, 40000)).toBe(1000);
  });
});

describe('mass', () => {
  const a320 = CATALOGUE.require('A320');

  it('helps when light and hurts when heavy', () => {
    expect(massFactor(a320, a320.mass.referenceKg)).toBeCloseTo(1, 9);
    expect(massFactor(a320, 50000)).toBeGreaterThan(1);
    expect(massFactor(a320, 77000)).toBeLessThan(1);
  });

  it('shows up in the climb rate', () => {
    const light = climbRateFpm(a320, 5000, 50000, false);
    const heavy = climbRateFpm(a320, 5000, 77000, false);
    expect(light).toBeGreaterThan(heavy);
  });

  it('works the other way round in the descent', () => {
    const light = descentRateFpm(a320, 10000, 50000, false, 0);
    const heavy = descentRateFpm(a320, 10000, 77000, false, 0);
    expect(heavy).toBeGreaterThan(light);
  });
});

describe('climb and descent rates', () => {
  const a320 = CATALOGUE.require('A320');

  it('fall off with altitude', () => {
    const low = climbRateFpm(a320, 1000, a320.mass.referenceKg, false);
    const high = climbRateFpm(a320, 14000, a320.mass.referenceKg, false);
    expect(low).toBeGreaterThan(high);
  });

  it('rise with altitude in the descent, as the true airspeed does', () => {
    const low = descentRateFpm(a320, 2000, a320.mass.referenceKg, false, 0);
    const high = descentRateFpm(a320, 14000, a320.mass.referenceKg, false, 0);
    expect(high).toBeGreaterThan(low);
  });

  it('are cut when the aircraft has to slow down as well', () => {
    const clean = descentRateFpm(a320, 10000, a320.mass.referenceKg, false, 0);
    const slight = descentRateFpm(a320, 10000, a320.mass.referenceKg, false, 5);
    const heavy = descentRateFpm(a320, 10000, a320.mass.referenceKg, false, 40);
    expect(slight).toBeLessThan(clean);
    expect(heavy).toBeLessThan(slight);
  });

  it('never fall below a flyable rate', () => {
    const c172 = CATALOGUE.require('C172');
    expect(climbRateFpm(c172, 15000, c172.mass.maximumKg, false)).toBeGreaterThanOrEqual(150);
  });

  it('are raised by the expedite factor in the profile', () => {
    const normal = climbRateFpm(a320, 5000, a320.mass.referenceKg, false);
    const quick = climbRateFpm(a320, 5000, a320.mass.referenceKg, true);
    expect(quick / normal).toBeCloseTo(a320.expediteFactor, 6);
  });
});

describe('acceleration limits', () => {
  const a320 = CATALOGUE.require('A320');

  it('are worst for accelerating in the climb and slowing in the descent', () => {
    expect(accelerationKtPerSec(a320, 'climb', true, 0)).toBeLessThan(
      accelerationKtPerSec(a320, 'cruise', true, 0),
    );
    expect(accelerationKtPerSec(a320, 'descent', false, 0)).toBeLessThan(
      accelerationKtPerSec(a320, 'cruise', false, 0),
    );
  });

  it('are cut by a steep turn only when accelerating', () => {
    expect(accelerationKtPerSec(a320, 'cruise', true, 25)).toBeLessThan(
      accelerationKtPerSec(a320, 'cruise', true, 0),
    );
    expect(accelerationKtPerSec(a320, 'cruise', false, 25)).toBe(
      accelerationKtPerSec(a320, 'cruise', false, 0),
    );
  });

  it('stay positive however steep the turn', () => {
    expect(accelerationKtPerSec(a320, 'climb', true, 25)).toBeGreaterThan(0);
  });
});

describe('fuel burn', () => {
  it('is highest in the climb and lowest in the descent', () => {
    const a320 = CATALOGUE.require('A320');
    expect(fuelBurnKgPerSec(a320, 'climb')).toBeGreaterThan(fuelBurnKgPerSec(a320, 'cruise'));
    expect(fuelBurnKgPerSec(a320, 'descent')).toBeLessThan(fuelBurnKgPerSec(a320, 'cruise'));
    expect(fuelBurnKgPerSec(a320, 'approach')).toBeGreaterThan(fuelBurnKgPerSec(a320, 'descent'));
  });

  it('scales with the size of the aeroplane', () => {
    expect(fuelBurnKgPerSec(CATALOGUE.require('B77W'), 'cruise')).toBeGreaterThan(
      fuelBurnKgPerSec(CATALOGUE.require('C172'), 'cruise') * 100,
    );
  });
});
