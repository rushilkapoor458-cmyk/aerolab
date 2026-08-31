import { describe, expect, it } from 'vitest';
import airspaceData from '../data/airspace.json';
import aircraftData from '../data/aircraft.json';
import wakeData from '../data/wake.json';
import { Airspace, RawAirspace } from './airspace.js';
import { PerformanceCatalogue, RawPerformance } from './performance.js';
import { Scenario, startTimeSec, validateScenario } from './scenario.js';
import { DEFAULT_SCENARIO_ID, SCENARIOS, findScenario } from './scenarios.js';
import { RawWakeMatrix, WakeMatrix } from './wake.js';
import { Simulation } from './world.js';

const AIRSPACE = new Airspace(airspaceData as unknown as RawAirspace);
const PERFORMANCE = new PerformanceCatalogue(aircraftData as unknown as RawPerformance);
const WAKE = new WakeMatrix(wakeData as unknown as RawWakeMatrix);

function sim(): Simulation {
  return new Simulation(AIRSPACE, PERFORMANCE, WAKE, 1);
}

describe('the shipped scenarios', () => {
  it('are the five in the brief', () => {
    expect(SCENARIOS.map((s) => s.id)).toEqual([
      'tutorial',
      'standard-day',
      'rush',
      'weather',
      'emergency',
    ]);
    expect(findScenario(DEFAULT_SCENARIO_ID)).toBeDefined();
    expect(findScenario('nonsense')).toBeUndefined();
  });

  it('all validate against the airspace and the aircraft catalogue', () => {
    for (const scenario of SCENARIOS) {
      expect(() => validateScenario(scenario, AIRSPACE, PERFORMANCE)).not.toThrow();
    }
  });

  it('all load into a simulation', () => {
    for (const scenario of SCENARIOS) {
      const world = sim();
      expect(() => world.loadScenario(scenario)).not.toThrow();
      expect(world.scenario?.id).toBe(scenario.id);
      expect(world.timeSec).toBe(startTimeSec(scenario));
      expect(world.runways.arrival).toBe(scenario.runways.arrival);
    }
  });

  it('give the tutorial two scripted arrivals and nothing else', () => {
    const scenario = findScenario('tutorial');
    expect(scenario).toBeDefined();
    if (scenario === undefined) return;
    expect(scenario.traffic.arrivalsPerHour).toBe(0);
    expect(scenario.traffic.departuresPerHour).toBe(0);
    expect(scenario.events.filter((e) => e.kind === 'arrival')).toHaveLength(2);
    expect(scenario.events.filter((e) => e.kind === 'departure')).toHaveLength(0);
  });

  it('give the rush forty-five movements an hour', () => {
    const scenario = findScenario('rush');
    if (scenario === undefined) throw new Error('missing');
    expect(scenario.traffic.arrivalsPerHour + scenario.traffic.departuresPerHour).toBe(45);
    expect(scenario.traffic.fleet.some((f) => f.type === 'B77W')).toBe(true);
  });

  it('give the standard day twenty movements an hour on one runway each way', () => {
    const scenario = findScenario('standard-day');
    if (scenario === undefined) throw new Error('missing');
    expect(scenario.traffic.arrivalsPerHour + scenario.traffic.departuresPerHour).toBe(20);
    expect(scenario.runways.arrival).toBe('29R');
    expect(scenario.runways.departure).toBe('29R');
  });

  it('give the weather scenario a runway change and short fuel', () => {
    const scenario = findScenario('weather');
    if (scenario === undefined) throw new Error('missing');
    expect(scenario.events.some((e) => e.kind === 'runway-change')).toBe(true);
    expect(scenario.events.filter((e) => e.kind === 'weather').length).toBeGreaterThan(1);
    expect(scenario.traffic.fuelFactor.min).toBeLessThan(0.6);
  });

  it('give the emergency scenario both failures', () => {
    const scenario = findScenario('emergency');
    if (scenario === undefined) throw new Error('missing');
    const kinds = scenario.events
      .filter((e): e is Extract<typeof e, { kind: 'emergency' }> => e.kind === 'emergency')
      .map((e) => e.emergency);
    expect(kinds).toContain('engine');
    expect(kinds).toContain('radio');
  });
});

describe('validation', () => {
  const base = (): Scenario => {
    const scenario = findScenario('standard-day');
    if (scenario === undefined) throw new Error('missing');
    return JSON.parse(JSON.stringify(scenario)) as Scenario;
  };

  it('reads the start time', () => {
    expect(startTimeSec({ ...base(), startTimeUtc: '10:00' })).toBe(36000);
    expect(startTimeSec({ ...base(), startTimeUtc: '00:05' })).toBe(300);
    expect(() => startTimeSec({ ...base(), startTimeUtc: '1000' })).toThrow(/bad startTimeUtc/);
  });

  it('rejects an unknown runway', () => {
    const scenario = { ...base(), runways: { arrival: '33', departure: '29' } };
    expect(() => validateScenario(scenario, AIRSPACE, PERFORMANCE)).toThrow(/unknown runway 33/);
  });

  it('rejects an unknown aircraft type', () => {
    const scenario = base();
    const broken = {
      ...scenario,
      traffic: { ...scenario.traffic, fleet: [{ type: 'B744', weight: 1 }] },
    };
    expect(() => validateScenario(broken, AIRSPACE, PERFORMANCE)).toThrow(/unknown aircraft type B744/);
  });

  it('rejects an entry fix with no STAR', () => {
    const scenario = base();
    const broken = {
      ...scenario,
      traffic: { ...scenario.traffic, entryFixes: ['PARAS'] },
    };
    expect(() => validateScenario(broken, AIRSPACE, PERFORMANCE)).toThrow(/no STAR starts there/);
  });

  it('rejects initial traffic placed outside the sector', () => {
    const scenario = base();
    const placement = {
      callsign: 'AIC999', type: 'A320', atFix: 'GUDUR', beyondNm: 40,
      altitudeFt: 9000, clearedAltitudeFt: 9000, iasKt: 280, clearedSpeedKt: 280,
      squawk: '4599', route: [],
    };
    const broken: Scenario = { ...scenario, initialTraffic: [placement] };
    expect(() => validateScenario(broken, AIRSPACE, PERFORMANCE))
      .toThrow(/AIC999 outside the sector/);
  });

  it('accepts initial traffic placed inside the sector', () => {
    const scenario = base();
    const placement = {
      callsign: 'AIC998', type: 'A320', atFix: 'GUDUR', beyondNm: -6,
      altitudeFt: 9000, clearedAltitudeFt: 9000, iasKt: 280, clearedSpeedKt: 280,
      squawk: '4598', route: ['TUMSA'],
    };
    const ok: Scenario = { ...scenario, initialTraffic: [placement] };
    expect(() => validateScenario(ok, AIRSPACE, PERFORMANCE)).not.toThrow();
  });

  it('rejects initial traffic routed via an unknown fix', () => {
    const scenario = base();
    const placement = {
      callsign: 'AIC997', type: 'A320', atFix: 'GUDUR', beyondNm: -6,
      altitudeFt: 9000, clearedAltitudeFt: 9000, iasKt: 280, clearedSpeedKt: 280,
      squawk: '4597', route: ['NOWHR'],
    };
    const broken: Scenario = { ...scenario, initialTraffic: [placement] };
    expect(() => validateScenario(broken, AIRSPACE, PERFORMANCE)).toThrow(/unknown fix NOWHR/);
  });

  it('rejects an unknown SID', () => {
    const scenario = base();
    const broken = {
      ...scenario,
      traffic: { ...scenario.traffic, departureSids: ['NOSID1A'] },
    };
    expect(() => validateScenario(broken, AIRSPACE, PERFORMANCE)).toThrow(/unknown SID NOSID1A/);
  });

  it('rejects an event that spawns an unknown type', () => {
    const scenario = base();
    const broken: Scenario = {
      ...scenario,
      events: [
        {
          atMin: 1,
          kind: 'arrival',
          callsign: 'TST1',
          type: 'B744',
          entryFix: 'GUDUR',
          altitudeFt: 9000,
          speedKt: 250,
        },
      ],
    };
    expect(() => validateScenario(broken, AIRSPACE, PERFORMANCE)).toThrow(/spawns unknown type/);
  });
});
