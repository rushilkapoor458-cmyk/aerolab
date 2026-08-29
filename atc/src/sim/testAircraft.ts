/**
 * Test support: a fully populated aircraft to vary from.
 *
 * Only the unit tests import this. Keeping one fixture here means adding a
 * field to `Aircraft` breaks one file rather than five.
 */

import aircraftData from '../data/aircraft.json';
import { PerformanceCatalogue, RawPerformance } from './performance.js';
import { Aircraft, Clearance } from './types.js';

/** Overrides for the fixture; the clearance may be given in part. */
export interface AircraftOverrides extends Partial<Omit<Aircraft, 'clearance'>> {
  clearance?: Partial<Clearance>;
}

export const TEST_CATALOGUE = new PerformanceCatalogue(aircraftData as unknown as RawPerformance);

let counter = 0;

export function makeTestAircraft(overrides: AircraftOverrides = {}, type = 'A320'): Aircraft {
  const profile = TEST_CATALOGUE.require(type);
  const base: Aircraft = {
    id: `ac${++counter}`,
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
    entryTimeSec: 0,
    entryPosition: { x: 0, y: 0 },
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
      descendVia: false,
    },
    route: [],
    procedure: null,
    phase: 'cruise',
    hold: null,
    approach: null,
    goAroundCount: 0,
    ground: null,
    departureRunway: null,
    emergency: 'none',
    performanceFactor: 1,
    history: [],
    sweepTimerSec: 4,
    handedOff: false,
    handedOffTo: null,
    handedOffFrequencyMhz: null,
  };
  return {
    ...base,
    ...overrides,
    // A clearance given in part keeps the rest of the fixture's defaults.
    clearance: { ...base.clearance, ...(overrides.clearance ?? {}) },
  };
}
