import { describe, expect, it } from 'vitest';
import airspaceData from '../data/airspace.json';
import aircraftData from '../data/aircraft.json';
import { Airspace, RawAirspace } from './airspace.js';
import { seedInitialTraffic } from './initialTraffic.js';
import { PerformanceCatalogue, RawPerformance } from './performance.js';
import { Simulation } from './world.js';

const PERFORMANCE = new PerformanceCatalogue(aircraftData as unknown as RawPerformance);

function build(seed = 1): Simulation {
  const airspace = new Airspace(airspaceData as unknown as RawAirspace);
  const sim = new Simulation(airspace, PERFORMANCE, seed);
  seedInitialTraffic(sim);
  return sim;
}

describe('airspace data', () => {
  it('loads and validates every procedure against the fixes it names', () => {
    expect(() => new Airspace(airspaceData as unknown as RawAirspace)).not.toThrow();
  });

  it('puts the final approach fix eight miles out on the localiser course', () => {
    const airspace = new Airspace(airspaceData as unknown as RawAirspace);
    const approach = airspace.approachForRunway('29');
    expect(approach).toBeDefined();
    const runway = airspace.runway('29');
    const faf = airspace.fix(approach?.finalApproachFix ?? '');
    expect(runway).toBeDefined();
    expect(faf).toBeDefined();
    if (runway === undefined || faf === undefined) return;
    const dx = faf.position.x - runway.threshold.x;
    const dy = faf.position.y - runway.threshold.y;
    expect(Math.hypot(dx, dy)).toBeCloseTo(8, 3);
  });

  it('reports a minimum safe altitude everywhere inside the sector', () => {
    const airspace = new Airspace(airspaceData as unknown as RawAirspace);
    expect(airspace.minimumSafeAltitudeFt({ x: 0, y: 0 })).toBeGreaterThan(0);
    expect(airspace.minimumSafeAltitudeFt({ x: -45, y: -30 })).toBeGreaterThan(
      airspace.minimumSafeAltitudeFt({ x: 10, y: 10 }),
    );
  });
});

describe('determinism', () => {
  it('the same seed reproduces the same traffic exactly', () => {
    const a = build(4242);
    const b = build(4242);
    a.step(600);
    b.step(600);
    expect(a.aircraft.map((x) => [x.callsign, x.position.x, x.position.y, x.altitudeFt])).toEqual(
      b.aircraft.map((x) => [x.callsign, x.position.x, x.position.y, x.altitudeFt]),
    );
  });

  it('stepping in small pieces matches stepping in one go', () => {
    const a = build(7);
    const b = build(7);
    a.step(120);
    for (let i = 0; i < 480; i++) b.step(0.25);
    for (let i = 0; i < a.aircraft.length; i++) {
      expect(a.aircraft[i]?.position.x).toBeCloseTo(b.aircraft[i]?.position.x ?? NaN, 6);
      expect(a.aircraft[i]?.position.y).toBeCloseTo(b.aircraft[i]?.position.y ?? NaN, 6);
    }
  });
});

describe('transmitting', () => {
  it('applies a chained instruction and reads it back', () => {
    const sim = build();
    expect(sim.transmit('AIC101 tl 270 d 90 s 250')).toBeNull();
    const ac = sim.find('AIC101');
    expect(ac?.clearance.headingDeg).toBe(270);
    expect(ac?.clearance.turn).toBe('left');
    expect(ac?.clearance.altitudeFt).toBe(9000);
    expect(ac?.clearance.speedKt).toBe(250);
    expect(ac?.clearance.lateralMode).toBe('heading');

    const last = sim.comms[sim.comms.length - 1];
    expect(last?.source).toBe('pilot');
    expect(last?.rejected).toBe(false);
    expect(last?.text).toMatch(/turn left heading 270/);
    expect(last?.text).toMatch(/AIC101$/);
  });

  it('rejects a callsign that is not on frequency', () => {
    const sim = build();
    const error = sim.transmit('XYZ999 tl 270');
    expect(error).toMatch(/No aircraft XYZ999/);
  });

  it('keeps the parse error out of the aircraft', () => {
    const sim = build();
    const before = sim.find('AIC101')?.clearance.headingDeg;
    expect(sim.transmit('AIC101 wibble 270')).toMatch(/do not recognise/);
    expect(sim.find('AIC101')?.clearance.headingDeg).toBe(before);
  });

  it('refuses a descent below the minimum safe altitude, with the reason', () => {
    const sim = build();
    const before = sim.find('AIC101')?.clearance.altitudeFt;
    sim.transmit('AIC101 d 20');
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(true);
    expect(last?.text).toMatch(/unable, the minimum safe altitude in this area is \d+ feet/);
    expect(sim.find('AIC101')?.clearance.altitudeFt).toBe(before);
  });

  it('queries a climb instruction given to an aircraft that is already above it', () => {
    const sim = build();
    sim.transmit('AIC101 c 50');
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(true);
    expect(last?.text).toMatch(/did you mean descend/);
  });

  it('refuses a level above the top of the sector', () => {
    const sim = build();
    sim.transmit('AIC101 c 200');
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/top of your airspace/);
  });

  it('refuses a fix it has never heard of, and keeps the old clearance', () => {
    const sim = build();
    sim.transmit('AIC101 dct NOWHR');
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(true);
    expect(last?.text).toMatch(/don't have NOWHR in the database/);
    expect(sim.find('AIC101')?.clearance.directFix).toBe('TUMSA');
  });

  it('accepts part of a transmission and refuses the rest', () => {
    const sim = build();
    sim.transmit('AIC101 tl 200 d 20');
    const ac = sim.find('AIC101');
    expect(ac?.clearance.headingDeg).toBe(200);
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.text).toMatch(/turn left heading 200/);
    expect(last?.text).toMatch(/unable/);
  });

  it('warns that the speed restriction still applies below ten thousand', () => {
    const sim = build();
    // SEJ301 is level at 7000 ft, so the rule bites.
    sim.transmit('SEJ301 s 280');
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/restricted to 250 below ten thousand/);
    sim.transmit('SEJ301 cancel speed restriction');
    expect(sim.comms[sim.comms.length - 1]?.rejected).toBe(false);
    expect(sim.find('SEJ301')?.clearance.speedRestrictionCancelled).toBe(true);
  });
});

describe('navigation', () => {
  it('sequences onto the next fix of the route once the first is passed', () => {
    const sim = build();
    const ac = sim.find('AIC101');
    expect(ac?.clearance.directFix).toBe('TUMSA');
    expect(ac?.route).toEqual(['SAHIB']);
    // Long enough to run from beyond GUDUR to TUMSA at close to 300 kt.
    sim.step(60 * 7);
    expect(sim.find('AIC101')?.clearance.directFix).toBe('SAHIB');
    expect(sim.comms.some((c) => c.text.includes('TUMSA passed'))).toBe(true);
  });

  it('a vectored aircraft holds its heading', () => {
    const sim = build();
    const before = sim.find('SEJ301')?.headingDeg ?? 0;
    sim.step(300);
    expect(sim.find('SEJ301')?.headingDeg).toBeCloseTo(before, 6);
  });
});

describe('runway selection', () => {
  it('picks the runway with the most headwind', () => {
    const sim = build();
    sim.weather.windDirectionDeg = 290;
    sim.weather.windSpeedKt = 15;
    expect(sim.suggestedRunways().arrival).toBe('29');
    sim.weather.windDirectionDeg = 100;
    expect(sim.suggestedRunways().arrival).toBe('10');
  });
});

describe('performance in the world', () => {
  it('gives every aircraft the profile for its type', () => {
    const sim = build();
    expect(sim.find('AIC101')?.profile.icao).toBe('A320');
    expect(sim.find('VTI872')?.wake).toBe('H');
    expect(sim.find('VTABC')?.wake).toBe('L');
    expect(sim.find('QTR578')?.profile.name).toMatch(/A350/);
  });

  it('refuses a type with no profile rather than inventing one', () => {
    const sim = build();
    expect(() =>
      sim.add({
        callsign: 'ZZZ1', type: 'B744', role: 'arrival',
        position: { x: 0, y: 0 }, altitudeFt: 5000, headingDeg: 90, iasKt: 250,
        clearedAltitudeFt: 5000, clearedSpeedKt: 250, squawk: '1000',
      }),
    ).toThrow(/no performance profile for B744/);
  });

  it('burns fuel and gets lighter as it flies', () => {
    const sim = build();
    const before = sim.find('AIC101');
    const fuelBefore = before?.fuelKg ?? 0;
    const massBefore = before?.massKg ?? 0;
    sim.step(600);
    const after = sim.find('AIC101');
    expect(after?.fuelKg).toBeLessThan(fuelBefore);
    expect(after?.massKg).toBeLessThan(massBefore);
  });

  it('lets a short-fuelled aircraft escalate on its own', () => {
    const sim = build();
    sim.step(60 * 25);
    const ac = sim.find('SEJ301');
    expect(ac?.fuelState).not.toBe('normal');
    expect(sim.comms.some((c) => /minimum fuel/.test(c.text))).toBe(true);
  });

  it('answers say fuel remaining', () => {
    const sim = build();
    sim.transmit('AIC101 say fuel');
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(false);
    expect(last?.text).toMatch(/kilos remaining/);
  });

  it('feels a different wind at different levels', () => {
    const sim = build();
    const low = sim.windAt(sim.airspace.airport.elevationFt);
    const high = sim.windAt(15000);
    expect(high.speedKt).toBeGreaterThan(low.speedKt + 20);
  });
});

describe('handing off', () => {
  it('acknowledges and leaves the frequency', () => {
    const sim = build();
    expect(sim.transmit('AIC101 contact tower 118.1')).toBeNull();
    const ac = sim.find('AIC101');
    expect(ac?.handedOff).toBe(true);
    expect(ac?.handedOffTo).toBe('tower');
    expect(ac?.handedOffFrequencyMhz).toBe(118.1);
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/over to tower on 118.1, good day/);
  });

  it('takes no further instructions once handed off', () => {
    const sim = build();
    sim.transmit('AIC101 contact tower 118.1');
    const error = sim.transmit('AIC101 tl 090');
    expect(error).toMatch(/no longer on this frequency/);
    expect(sim.find('AIC101')?.clearance.headingDeg).not.toBe(90);
  });

  it('drops off the scope once it is out of the sector', () => {
    const sim = build();
    // Turn it round and send it back out the way it came.
    sim.transmit('AIC101 fh 112');
    sim.step(120);
    sim.transmit('AIC101 contact delhi control 127.9');
    expect(sim.find('AIC101')).toBeDefined();
    sim.step(60 * 10);
    expect(sim.find('AIC101')).toBeUndefined();
    expect(sim.comms.some((c) => /AIC101 has left the sector/.test(c.text))).toBe(true);
  });

  it('keeps an aircraft that has not been handed off, wherever it goes', () => {
    const sim = build();
    sim.transmit('AIC101 fh 112');
    sim.step(60 * 15);
    expect(sim.find('AIC101')).toBeDefined();
  });
});

describe('emergency squawk', () => {
  it('will not let the controller overwrite it', () => {
    const sim = build();
    const ac = sim.find('SEJ301');
    if (ac === undefined) throw new Error('SEJ301 missing');
    ac.fuelState = 'emergency';
    ac.squawk = '7700';
    sim.transmit('SEJ301 squawk 4520');
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(true);
    expect(ac.squawk).toBe('7700');
  });
});
