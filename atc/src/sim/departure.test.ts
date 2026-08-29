import { describe, expect, it } from 'vitest';
import airspaceData from '../data/airspace.json';
import aircraftData from '../data/aircraft.json';
import wakeData from '../data/wake.json';
import { Airspace, RawAirspace } from './airspace.js';
import {
  initialClimbSpeedKt,
  placeAtHoldingPoint,
  rotationSpeedKt,
  stepGroundRoll,
  takeoffAccelerationKtPerSec,
} from './departure.js';
import { distanceNm } from './geo.js';
import { PerformanceCatalogue, RawPerformance } from './performance.js';
import { findScenario } from './scenarios.js';
import { makeTestAircraft, TEST_CATALOGUE } from './testAircraft.js';
import { RawWakeMatrix, WakeMatrix } from './wake.js';
import { Simulation } from './world.js';

const AIRSPACE = new Airspace(airspaceData as unknown as RawAirspace);
const PERFORMANCE = new PerformanceCatalogue(aircraftData as unknown as RawPerformance);
const WAKE = new WakeMatrix(wakeData as unknown as RawWakeMatrix);
const RUNWAY_29 = AIRSPACE.runway('29');
if (RUNWAY_29 === undefined) throw new Error('runway 29 missing');
const RUNWAY = RUNWAY_29;
const CALM = { fromTrueDeg: 0, speedKt: 0 };

describe('take-off performance', () => {
  it('accelerates a jet faster than a piston', () => {
    expect(takeoffAccelerationKtPerSec(TEST_CATALOGUE.require('A320'))).toBeGreaterThan(
      takeoffAccelerationKtPerSec(TEST_CATALOGUE.require('C172')),
    );
  });

  it('rotates above the approach speed and cleans up above that', () => {
    const profile = TEST_CATALOGUE.require('A320');
    expect(rotationSpeedKt(profile)).toBeGreaterThan(profile.speeds.approachIasKt);
    expect(initialClimbSpeedKt(profile)).toBeGreaterThanOrEqual(rotationSpeedKt(profile));
  });
});

describe('the take-off roll', () => {
  function ready(type = 'A320') {
    const ac = makeTestAircraft({ role: 'departure' }, type);
    placeAtHoldingPoint(ac, RUNWAY, AIRSPACE.airport.magneticVariationDeg);
    return ac;
  }

  it('puts the aircraft on the threshold, stationary', () => {
    const ac = ready();
    expect(ac.ground).toBe('queue');
    expect(ac.iasKt).toBe(0);
    expect(ac.groundspeedKt).toBe(0);
    expect(ac.departureRunway).toBe('29');
    expect(distanceNm(ac.position, RUNWAY.threshold)).toBeCloseTo(0, 9);
  });

  it('does not move while it is queued or lined up', () => {
    const ac = ready();
    stepGroundRoll(ac, 10, { wind: CALM, magneticVariationDeg: 0, runway: RUNWAY });
    ac.ground = 'lineup';
    stepGroundRoll(ac, 10, { wind: CALM, magneticVariationDeg: 0, runway: RUNWAY });
    expect(ac.iasKt).toBe(0);
    expect(distanceNm(ac.position, RUNWAY.threshold)).toBeCloseTo(0, 9);
  });

  it('accelerates down the runway and rotates', () => {
    const ac = ready();
    ac.ground = 'takeoff';
    let airborne = false;
    let seconds = 0;
    while (!airborne && seconds < 120) {
      airborne = stepGroundRoll(ac, 0.25, {
        wind: CALM,
        magneticVariationDeg: 0,
        runway: RUNWAY,
      }).airborne;
      seconds += 0.25;
    }
    expect(airborne).toBe(true);
    expect(ac.ground).toBeNull();
    expect(ac.phase).toBe('climb');
    expect(ac.iasKt).toBeGreaterThanOrEqual(rotationSpeedKt(ac.profile));
    // A transport jet uses a mile or two of runway getting to rotation.
    const roll = distanceNm(ac.position, RUNWAY.threshold);
    expect(roll).toBeGreaterThan(0.4);
    expect(roll).toBeLessThan(2.5);
  });

  it('needs less ground run into a headwind', () => {
    const headwind = { fromTrueDeg: RUNWAY.trueHeadingDeg, speedKt: 30 };
    const rolls: number[] = [];
    for (const wind of [CALM, headwind]) {
      const ac = ready();
      ac.ground = 'takeoff';
      for (let i = 0; i < 400 && ac.ground !== null; i++) {
        stepGroundRoll(ac, 0.25, { wind, magneticVariationDeg: 0, runway: RUNWAY });
      }
      rolls.push(distanceNm(ac.position, RUNWAY.threshold));
    }
    const [calm, into] = rolls;
    expect(into ?? 0).toBeLessThan(calm ?? 0);
  });

  it('a light aircraft is off the ground sooner than a jet', () => {
    const distances: number[] = [];
    for (const type of ['A320', 'C172']) {
      const ac = ready(type);
      ac.ground = 'takeoff';
      for (let i = 0; i < 800 && ac.ground !== null; i++) {
        stepGroundRoll(ac, 0.25, { wind: CALM, magneticVariationDeg: 0, runway: RUNWAY });
      }
      distances.push(distanceNm(ac.position, RUNWAY.threshold));
    }
    const [jet, light] = distances;
    expect(light ?? 0).toBeLessThan(jet ?? 0);
  });
});

describe('departure clearances', () => {
  function launchable(): { sim: Simulation; callsign: string } {
    const scenario = findScenario('standard-day');
    if (scenario === undefined) throw new Error('missing scenario');
    const sim = new Simulation(AIRSPACE, PERFORMANCE, WAKE, scenario.seed);
    sim.loadScenario(scenario);
    for (let i = 0; i < 60 && !sim.aircraft.some((ac) => ac.ground === 'queue'); i++) sim.step(10);
    const waiting = sim.aircraft.find((ac) => ac.ground === 'queue');
    if (waiting === undefined) throw new Error('no departure appeared');
    return { sim, callsign: waiting.callsign };
  }

  it('lines up and then takes off', () => {
    const { sim, callsign } = launchable();
    expect(sim.transmit(`${callsign} line up and wait runway 29`)).toBeNull();
    expect(sim.find(callsign)?.ground).toBe('lineup');
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/lining up and waiting runway 29/);

    expect(sim.transmit(`${callsign} cleared for takeoff`)).toBeNull();
    expect(sim.find(callsign)?.ground).toBe('takeoff');

    sim.step(90);
    const ac = sim.find(callsign);
    expect(ac?.ground).toBeNull();
    expect(ac?.altitudeFt).toBeGreaterThan(AIRSPACE.airport.elevationFt);
    expect(sim.comms.some((c) => /airborne/.test(c.text))).toBe(true);
  });

  it('refuses to line up on an occupied runway', () => {
    const { sim, callsign } = launchable();
    sim.occupyRunway('29', 120);
    sim.transmit(`${callsign} luw 29`);
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(true);
    expect(last?.text).toMatch(/still occupied/);
    expect(sim.find(callsign)?.ground).toBe('queue');
  });

  it('takes a heading to fly after departure while still on the ground', () => {
    const { sim, callsign } = launchable();
    sim.transmit(`${callsign} fh 270`);
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/after departure, heading 270/);
    expect(sim.find(callsign)?.clearance.headingDeg).toBe(270);
  });

  it('refuses a departure clearance to something already flying', () => {
    const { sim, callsign } = launchable();
    sim.transmit(`${callsign} cleared for takeoff`);
    sim.step(90);
    sim.transmit(`${callsign} luw 29`);
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/already airborne/);
  });

  it('counts a departure once it leaves the sector', () => {
    const { sim, callsign } = launchable();
    sim.transmit(`${callsign} cleared for takeoff`);
    sim.step(60);
    sim.transmit(`${callsign} c 150`);
    sim.transmit(`${callsign} contact delhi control 127.9`);
    expect(sim.departures).toBe(0);
    for (let i = 0; i < 200 && sim.find(callsign) !== undefined; i++) sim.step(10);
    expect(sim.find(callsign)).toBeUndefined();
    expect(sim.departures).toBe(1);
  });
});
