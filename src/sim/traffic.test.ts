import { describe, expect, it } from 'vitest';
import airspaceData from '../data/airspace.json';
import aircraftData from '../data/aircraft.json';
import wakeData from '../data/wake.json';
import { Airspace, RawAirspace } from './airspace.js';
import { distanceNm, pointInPolygon } from './geo.js';
import { PerformanceCatalogue, RawPerformance } from './performance.js';
import { findScenario } from './scenarios.js';
import { starFrom } from './traffic.js';
import { RawWakeMatrix, WakeMatrix } from './wake.js';
import { Simulation } from './world.js';

const AIRSPACE = new Airspace(airspaceData as unknown as RawAirspace);
const PERFORMANCE = new PerformanceCatalogue(aircraftData as unknown as RawPerformance);
const WAKE = new WakeMatrix(wakeData as unknown as RawWakeMatrix);

function run(id: string, seconds: number): Simulation {
  const scenario = findScenario(id);
  if (scenario === undefined) throw new Error(`no scenario ${id}`);
  const sim = new Simulation(AIRSPACE, PERFORMANCE, WAKE, scenario.seed);
  sim.loadScenario(scenario);
  sim.step(seconds);
  return sim;
}

describe('generating traffic', () => {
  it('produces roughly the rate the scenario asks for', () => {
    const sim = run('standard-day', 3600);
    const created = sim.aircraft.length + sim.arrivals + sim.departures;
    // Twenty an hour, with jitter and with some still airborne at the end.
    expect(created).toBeGreaterThan(12);
    expect(created).toBeLessThan(30);
  });

  it('produces more traffic in the rush than on a standard day', () => {
    const standard = run('standard-day', 1800);
    const rush = run('rush', 1800);
    expect(rush.aircraft.length).toBeGreaterThan(standard.aircraft.length);
  });

  it('starts arrivals inside the sector on a published STAR', () => {
    const sim = run('standard-day', 900);
    const arrivals = sim.aircraft.filter((ac) => ac.role === 'arrival');
    expect(arrivals.length).toBeGreaterThan(0);
    for (const ac of arrivals) {
      expect(ac.procedure).not.toBeNull();
      if (ac.procedure !== null) expect(AIRSPACE.star(ac.procedure)).toBeDefined();
    }
    // The first one to appear was inside the boundary when it did.
    const first = arrivals[0];
    if (first !== undefined) {
      expect(distanceNm(first.entryPosition, { x: 0, y: 0 })).toBeLessThan(52);
      expect(pointInPolygon(first.entryPosition, AIRSPACE.sector.boundary)).toBe(true);
    }
  });

  it('puts departures at the holding point on a SID', () => {
    const sim = run('standard-day', 900);
    const departures = sim.aircraft.filter((ac) => ac.role === 'departure');
    expect(departures.length).toBeGreaterThan(0);
    for (const ac of departures) {
      if (ac.ground === null) continue;
      expect(ac.ground).toBe('queue');
      expect(ac.departureRunway).toBe(sim.runways.departure);
      expect(ac.iasKt).toBe(0);
      expect(ac.procedure).not.toBeNull();
    }
  });

  it('gives every aircraft a unique callsign and a legal squawk', () => {
    const sim = run('rush', 1800);
    const callsigns = sim.aircraft.map((ac) => ac.callsign);
    expect(new Set(callsigns).size).toBe(callsigns.length);
    for (const ac of sim.aircraft) {
      expect(ac.squawk).toMatch(/^[1-6][0-7][0-7][0-7]$/);
    }
  });

  it('does not let the departure queue grow without bound', () => {
    const sim = run('rush', 3600);
    const queued = sim.aircraft.filter((ac) => ac.ground === 'queue' || ac.ground === 'lineup');
    expect(queued.length).toBeLessThanOrEqual(6);
  });

  it('generates nothing at all for the tutorial beyond its script', () => {
    const sim = run('tutorial', 1800);
    expect(sim.aircraft.length + sim.arrivals).toBe(2);
  });

  it('is reproducible from the scenario seed', () => {
    const a = run('standard-day', 1200);
    const b = run('standard-day', 1200);
    expect(a.aircraft.map((ac) => [ac.callsign, ac.type, Math.round(ac.position.x * 1000)])).toEqual(
      b.aircraft.map((ac) => [ac.callsign, ac.type, Math.round(ac.position.x * 1000)]),
    );
  });
});

describe('finding the STAR for an entry fix', () => {
  it('matches by boundary fix, case insensitively', () => {
    expect(starFrom(AIRSPACE, 'GUDUR')?.ident).toBe('GUDUR1A');
    expect(starFrom(AIRSPACE, 'gudur')?.ident).toBe('GUDUR1A');
    expect(starFrom(AIRSPACE, 'PARAS')).toBeUndefined();
  });
});

describe('scenario events', () => {
  it('changes the weather and rolls the ATIS letter', () => {
    const sim = run('weather', 60 * 13);
    expect(sim.weather.atisLetter).not.toBe('F');
    expect(sim.weather.windDirectionDeg).toBe(340);
    expect(sim.comms.some((c) => /New ATIS, information/.test(c.text))).toBe(true);
  });

  it('changes the runway when the wind demands it', () => {
    const sim = run('weather', 60 * 23);
    expect(sim.runways.arrival).toBe('11');
    expect(sim.comms.some((c) => /Runway change/.test(c.text))).toBe(true);
  });

  it('fires an engine failure on a departure, once one is airborne', () => {
    const sim = run('emergency', 60 * 6);
    // Launch whatever is waiting, as a controller would.
    for (let minute = 0; minute < 10; minute++) {
      for (const ac of sim.aircraft) {
        if (ac.ground === 'queue' || ac.ground === 'lineup') {
          sim.transmit(`${ac.callsign} cleared for takeoff`);
          break;
        }
      }
      sim.step(60);
    }
    const failed = sim.aircraft.find((ac) => ac.emergency === 'engine');
    expect(failed).toBeDefined();
    expect(failed?.squawk).toBe('7700');
    expect(failed?.performanceFactor).toBeLessThan(1);
    expect(sim.comms.some((c) => /MAYDAY MAYDAY MAYDAY/.test(c.text))).toBe(true);
  });

  it('defers an emergency it cannot place, rather than dropping it', () => {
    // Nothing is ever launched, so the departure emergency has no target.
    const sim = run('emergency', 60 * 12);
    expect(sim.aircraft.some((ac) => ac.emergency === 'engine')).toBe(false);
    expect(sim.comms.some((c) => /dropped/.test(c.text))).toBe(false);
  });

  it('fires a radio failure on an arrival that then ignores instructions', () => {
    const sim = run('emergency', 60 * 28);
    const nordo = sim.aircraft.find((ac) => ac.emergency === 'radio');
    expect(nordo).toBeDefined();
    if (nordo === undefined) return;
    expect(nordo.squawk).toBe('7600');

    const before = nordo.clearance.headingDeg;
    sim.transmit(`${nordo.callsign} fh 090`);
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/does not answer/);
    expect(nordo.clearance.headingDeg).toBe(before);
  });
});
