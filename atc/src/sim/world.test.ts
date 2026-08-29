import { describe, expect, it } from 'vitest';
import airspaceData from '../data/airspace.json';
import aircraftData from '../data/aircraft.json';
import wakeData from '../data/wake.json';
import { Airspace, RawAirspace } from './airspace.js';
import { alongTrackNm, crossTrackNm, distanceNm, movePoint, pointInPolygon } from './geo.js';
import { seedInitialTraffic } from './testTraffic.js';
import { PerformanceCatalogue, RawPerformance } from './performance.js';
import { RawWakeMatrix, WakeMatrix } from './wake.js';
import { Simulation } from './world.js';

const PERFORMANCE = new PerformanceCatalogue(aircraftData as unknown as RawPerformance);
const WAKE = new WakeMatrix(wakeData as unknown as RawWakeMatrix);

function build(seed = 1): Simulation {
  const airspace = new Airspace(airspaceData as unknown as RawAirspace);
  const sim = new Simulation(airspace, PERFORMANCE, WAKE, seed);
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
    expect(airspace.minimumSafeAltitudeFt({ x: -45, y: -30 }) ?? 0).toBeGreaterThan(
      airspace.minimumSafeAltitudeFt({ x: 10, y: 10 }) ?? 0,
    );
  });

  it('publishes nothing outside the grid rather than inventing a figure', () => {
    const airspace = new Airspace(airspaceData as unknown as RawAirspace);
    expect(airspace.minimumSafeAltitudeFt({ x: 0, y: 200 })).toBeNull();
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

/* --------------------------------------------------------------- approach */

/** Put an aircraft on the extended centreline of a runway. */
function placeOnFinal(
  sim: Simulation,
  callsign: string,
  distanceNm: number,
  offsetNm: number,
  altitudeFt: number,
  trackOffsetDeg = 0,
  iasKt = 190,
): void {
  const runway = sim.airspace.runway('29');
  if (runway === undefined) throw new Error('runway 29 missing');
  const reciprocal = (runway.trueHeadingDeg + 180) % 360;
  const centreline = movePoint(runway.threshold, reciprocal, distanceNm);
  const right = (runway.trueHeadingDeg + 90) % 360;
  const position = movePoint(centreline, right, offsetNm);
  sim.add({
    callsign,
    type: 'A320',
    role: 'arrival',
    position,
    altitudeFt,
    headingDeg: sim.airspace.toMagnetic(runway.trueHeadingDeg + trackOffsetDeg),
    iasKt,
    clearedAltitudeFt: altitudeFt,
    clearedSpeedKt: iasKt,
    squawk: '5001',
  });
}

describe('the ILS', () => {
  it('captures, flies the slope and lands', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST1', 13, 0.1, 3000, -10);
    expect(sim.transmit('TEST1 ils 29')).toBeNull();
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/cleared ILS runway 29 approach/);

    for (let i = 0; i < 60 && sim.find('TEST1') !== undefined; i++) sim.step(10);

    expect(sim.find('TEST1')).toBeUndefined();
    expect(sim.arrivals).toBe(1);
    expect(sim.comms.some((c) => /localiser established/.test(c.text))).toBe(true);
    expect(sim.comms.some((c) => /glideslope established/.test(c.text))).toBe(true);
    expect(sim.comms.some((c) => /landed runway 29/.test(c.text))).toBe(true);
  });

  it('blows through the localiser on a bad intercept', () => {
    const sim = build();
    sim.aircraft = [];
    // Crossing the centreline at ninety degrees, well outside the capture angle.
    placeOnFinal(sim, 'TEST2', 12, -3, 3000, 90);
    sim.transmit('TEST2 ils 29');
    sim.step(180);

    const ac = sim.find('TEST2');
    expect(ac).toBeDefined();
    expect(ac?.approach?.localiserCaptured).toBe(false);
    // It started left of course and is now right of it: straight through.
    const runway = sim.airspace.runway('29');
    if (ac === undefined || runway === undefined) throw new Error('missing');
    expect(crossTrackNm(ac.position, runway.threshold, runway.trueHeadingDeg)).toBeGreaterThan(0);
    expect(sim.comms.some((c) => /going through the localiser/.test(c.text))).toBe(true);
  });

  it('does not capture the glideslope from above', () => {
    const sim = build();
    sim.aircraft = [];
    // On the centreline but two thousand feet above the path at 8 NM.
    placeOnFinal(sim, 'TEST3', 9, 0.05, 5500);
    sim.transmit('TEST3 ils 29');
    sim.step(60);
    const ac = sim.find('TEST3');
    expect(ac?.approach?.localiserCaptured).toBe(true);
    expect(ac?.approach?.glideslopeCaptured).toBe(false);
  });

  it('goes around at the missed approach point if it never got the slope', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST4', 9, 0.05, 5500); // High, so the slope stays below it.
    sim.transmit('TEST4 ils 29');
    for (let i = 0; i < 90 && (sim.find('TEST4')?.goAroundCount ?? 0) === 0; i++) sim.step(5);
    const ac = sim.find('TEST4');
    expect(ac?.goAroundCount).toBe(1);
    expect(ac?.approach).toBeNull();
    expect(sim.arrivals).toBe(0);
    expect(sim.goArounds).toBe(1);
    expect(sim.comms.some((c) => /going around/.test(c.text))).toBe(true);
  });

  it('goes around when it is too fast at the gate', () => {
    const sim = build();
    sim.aircraft = [];
    // On the slope at three miles but still doing 200 kt: not stable.
    placeOnFinal(sim, 'TEST7', 3.2, 0, 827 + 3.2 * 318.4, 0, 200);
    sim.transmit('TEST7 ils 29');
    sim.step(15); // Long enough to sink through the gate at a thousand feet.
    expect(sim.find('TEST7')?.goAroundCount).toBe(1);
    expect(sim.comms.some((c) => /too fast to be stable/.test(c.text))).toBe(true);
  });

  it('goes around when the runway is still occupied', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'LEAD', 2, 0, 827 + 2 * 318.4, 0, 140);
    sim.transmit('LEAD ils 29');
    for (let i = 0; i < 60 && sim.arrivals === 0; i++) sim.step(5);
    expect(sim.arrivals).toBe(1);
    expect(sim.isRunwayOccupied('29')).toBe(true);

    // The next one arrives at the gate while the runway is still blocked.
    placeOnFinal(sim, 'TRAIL', 4, 0, 827 + 4 * 318.4, 0, 140);
    sim.transmit('TRAIL ils 29');
    for (let i = 0; i < 20 && sim.goArounds === 0; i++) sim.step(5);
    expect(sim.goArounds).toBe(1);
    expect(sim.comms.some((c) => /runway is still occupied/.test(c.text))).toBe(true);
  });

  it('takes a go-around on instruction', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST5', 10, 0, 3000);
    sim.transmit('TEST5 ils 29');
    sim.step(60);
    expect(sim.transmit('TEST5 go around')).toBeNull();
    const ac = sim.find('TEST5');
    expect(ac?.approach).toBeNull();
    expect(ac?.clearance.altitudeFt).toBe(4000);
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/going around/);
  });

  it('refuses a go-around from an aircraft that is not on one', () => {
    const sim = build();
    sim.transmit('AIC101 go around');
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(true);
    expect(last?.text).toMatch(/not on an approach/);
  });

  it('refuses a runway with no published approach', () => {
    const sim = build();
    sim.transmit('AIC101 ils 33');
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/33 is not a runway here/);
  });

  it('a vector cancels the approach', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST6', 12, 0, 3000);
    sim.transmit('TEST6 ils 29');
    expect(sim.find('TEST6')?.approach).not.toBeNull();
    sim.transmit('TEST6 tl 180');
    expect(sim.find('TEST6')?.approach).toBeNull();
  });
});

/* ------------------------------------------------------------------- hold */

describe('holding', () => {
  it('flies a racetrack that stays near the fix', () => {
    const sim = build();
    expect(sim.transmit('AIC101 hold at GUDUR as published')).toBeNull();
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/hold at GUDUR as published/);

    const gudur = sim.airspace.fix('GUDUR');
    if (gudur === undefined) throw new Error('GUDUR missing');
    let worst = 0;
    for (let i = 0; i < 120; i++) {
      sim.step(10);
      const ac = sim.find('AIC101');
      if (ac === undefined) break;
      worst = Math.max(worst, distanceNm(ac.position, gudur.position));
    }
    expect(worst).toBeLessThan(22);
    expect(sim.find('AIC101')?.hold?.leg).toBeDefined();
    expect(sim.comms.some((c) => /established in the hold at GUDUR/.test(c.text))).toBe(true);
  });

  it('takes an expect further clearance time', () => {
    const sim = build();
    sim.transmit('AIC101 hold at GUDUR as published expect further clearance 1420');
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/expect further clearance 1420/);
    expect(sim.find('AIC101')?.hold?.efcTimeSec).toBe(14 * 3600 + 20 * 60);
  });

  it('refuses a fix with no published hold', () => {
    const sim = build();
    sim.transmit('AIC101 hold at PARAS');
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(true);
    expect(last?.text).toMatch(/no published hold at PARAS/);
  });

  it('leaves the hold when given a vector', () => {
    const sim = build();
    sim.transmit('AIC101 hold at GUDUR');
    sim.step(60);
    sim.transmit('AIC101 fh 270');
    expect(sim.find('AIC101')?.hold).toBeNull();
    expect(sim.find('AIC101')?.clearance.lateralMode).toBe('heading');
  });
});

/* --------------------------------------------------------- descend via */

describe('descend via the arrival', () => {
  it('applies the published restrictions as it sequences', () => {
    const sim = build();
    expect(sim.transmit('AIC101 descend via the arrival')).toBeNull();
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/descend via the GUDUR1A arrival/);
    // TUMSA is published at or below 10,000 and 250 kt.
    const ac = sim.find('AIC101');
    expect(ac?.clearance.altitudeFt).toBe(10000);
    expect(ac?.clearance.speedKt).toBe(250);

    sim.step(60 * 8);
    const later = sim.find('AIC101');
    expect(later?.clearance.directFix).toBe('SAHIB');
    expect(later?.clearance.altitudeFt).toBe(7000);
  });

  it('refuses when the aircraft is on vectors', () => {
    const sim = build();
    sim.transmit('AIC101 fh 270');
    sim.transmit('AIC101 descend via the arrival');
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(true);
    expect(last?.text).toMatch(/not on the arrival any more/);
  });
});

describe('proceeding direct', () => {
  it('cuts the corner and keeps the rest of the route', () => {
    const sim = build();
    const ac = sim.find('VTI872');
    expect(ac?.clearance.directFix).toBe('ALGAN');
    expect(ac?.route).toEqual(['DAULA']);
    sim.transmit('VTI872 dct DAULA');
    expect(sim.find('VTI872')?.clearance.directFix).toBe('DAULA');
    expect(sim.find('VTI872')?.route).toEqual([]);
    expect(sim.find('VTI872')?.procedure).toBe('BUXOR1J');
  });

  it('does not leave the same fix sitting in the route', () => {
    const sim = build();
    sim.transmit('AIC101 dct SAHIB');
    const ac = sim.find('AIC101');
    expect(ac?.route).not.toContain('SAHIB');
    sim.step(60 * 20);
    const passes = sim.comms.filter((c) => /SAHIB passed/.test(c.text));
    expect(passes.length).toBeLessThanOrEqual(1);
  });

  it('takes the aircraft off the procedure when the fix is not on it', () => {
    const sim = build();
    sim.transmit('AIC101 dct KIRAN');
    const ac = sim.find('AIC101');
    expect(ac?.procedure).toBeNull();
    expect(ac?.route).toEqual([]);
  });
});

describe('holding, reported once', () => {
  it('calls established on entry and not on every circuit', () => {
    const sim = build();
    sim.transmit('AIC101 hold at GUDUR as published');
    sim.step(60 * 25);
    const calls = sim.comms.filter((c) => /established in the hold/.test(c.text));
    expect(calls).toHaveLength(1);
    expect(sim.find('AIC101')?.hold?.established).toBe(true);
  });
});

describe('speed on the approach', () => {
  it('accepts a speed below the clean minimum once cleared for the approach', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST8', 10, 0, 3000);
    sim.transmit('TEST8 s 180');
    expect(sim.comms[sim.comms.length - 1]?.rejected).toBe(true);

    sim.transmit('TEST8 ils 29');
    sim.transmit('TEST8 s 180');
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(false);
    expect(sim.find('TEST8')?.clearance.speedKt).toBe(180);
  });

  it('still refuses a speed below the final approach speed', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST9', 10, 0, 3000);
    sim.transmit('TEST9 ils 29');
    sim.transmit('TEST9 s 120');
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(true);
    expect(last?.text).toMatch(/below our approach speed of 138/);
  });
});

/* ------------------------------------------------------------- safety net */

describe('the safety net in the world', () => {
  it('runs on its own one second cycle', () => {
    const sim = build();
    sim.aircraft = [];
    sim.add({
      callsign: 'AAA1', type: 'A320', role: 'arrival', position: { x: 0, y: 10 },
      altitudeFt: 7000, headingDeg: 90, iasKt: 250,
      clearedAltitudeFt: 7000, clearedSpeedKt: 250, squawk: '1001',
    });
    sim.add({
      callsign: 'BBB2', type: 'A320', role: 'arrival', position: { x: 1.5, y: 10 },
      altitudeFt: 7300, headingDeg: 90, iasKt: 250,
      clearedAltitudeFt: 7300, clearedSpeedKt: 250, squawk: '1002',
    });
    expect(sim.safety.alerts).toHaveLength(0);
    sim.step(2);
    const alert = sim.safety.alerts.find((a) => a.kind === 'stca');
    expect(alert?.severity).toBe('warning');
    expect(sim.safety.violations).toHaveLength(1);
  });

  it('produces the same alerts from the same seed', () => {
    const a = build(99);
    const b = build(99);
    a.step(300);
    b.step(300);
    expect(a.safety.alerts.map((x) => x.id)).toEqual(b.safety.alerts.map((x) => x.id));
    expect(a.safety.violations.length).toBe(b.safety.violations.length);
  });

  it('warns when an unhandled aircraft leaves the sector', () => {
    const sim = build();
    sim.transmit('AIC101 fh 112');
    sim.step(60 * 12);
    const exit = sim.safety.alerts.find((x) => x.kind === 'sector-exit');
    expect(exit).toBeDefined();
    expect(sim.safety.violations.some((v) => v.kind === 'sector-exit')).toBe(true);
  });

  it('stops warning once the aircraft is handed off', () => {
    const sim = build();
    sim.transmit('AIC101 fh 112');
    sim.step(60 * 12);
    expect(sim.safety.alerts.some((x) => x.kind === 'sector-exit')).toBe(true);
    sim.transmit('AIC101 contact delhi control 127.9');
    sim.step(2);
    expect(sim.safety.alerts.some((x) => x.kind === 'sector-exit')).toBe(false);
  });
});

/* ------------------------------------------------------------------ score */

describe('the session score', () => {
  it('starts empty', () => {
    const sim = build();
    const score = sim.score();
    expect(score.arrivals).toBe(0);
    expect(score.movementsPerHour).toBe(0);
    expect(score.totalViolations).toBe(0);
    expect(score.onFrequency).toBe(6);
  });

  it('counts a landing, its delay and the fuel it burnt', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST10', 12, 0, 3000, 0, 180);
    sim.transmit('TEST10 ils 29');
    for (let i = 0; i < 80 && sim.arrivals === 0; i++) sim.step(10);

    const score = sim.score();
    expect(score.arrivals).toBe(1);
    expect(score.movements).toBe(1);
    expect(score.movementsPerHour).toBeGreaterThan(0);
    expect(score.fuelBurntKg).toBeGreaterThan(0);
    // Twelve miles flown straight in: the delay against a direct run is small.
    expect(score.averageDelaySec).toBeLessThan(120);
  });

  it('charges a delay for a long vector', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST11', 12, 0, 3000, 0, 180);
    // Send it away from the field for four minutes before turning it back.
    sim.transmit('TEST11 fh 112');
    sim.step(60 * 4);
    sim.transmit('TEST11 fh 292');
    sim.step(60 * 5);
    sim.transmit('TEST11 ils 29');
    for (let i = 0; i < 120 && sim.arrivals === 0; i++) sim.step(10);
    expect(sim.arrivals).toBe(1);
    expect(sim.score().averageDelaySec).toBeGreaterThan(120);
  });

  it('counts what was broken', () => {
    const sim = build();
    sim.aircraft = [];
    sim.add({
      callsign: 'AAA1', type: 'A320', role: 'arrival', position: { x: 0, y: 10 },
      altitudeFt: 7000, headingDeg: 90, iasKt: 250,
      clearedAltitudeFt: 7000, clearedSpeedKt: 250, squawk: '1001',
    });
    sim.add({
      callsign: 'BBB2', type: 'A320', role: 'arrival', position: { x: 1, y: 10 },
      altitudeFt: 7000, headingDeg: 90, iasKt: 250,
      clearedAltitudeFt: 7000, clearedSpeedKt: 250, squawk: '1002',
    });
    sim.step(2);
    expect(sim.score().separationLosses).toBe(1);
    expect(sim.score().totalViolations).toBe(1);
  });

  it('logs the violation with the values at the closest point', () => {
    const sim = build();
    sim.aircraft = [];
    sim.add({
      callsign: 'AAA1', type: 'A320', role: 'arrival', position: { x: 0, y: 10 },
      altitudeFt: 7000, headingDeg: 90, iasKt: 250,
      clearedAltitudeFt: 7000, clearedSpeedKt: 250, squawk: '1001',
    });
    sim.add({
      callsign: 'BBB2', type: 'A320', role: 'arrival', position: { x: 2.5, y: 10 },
      altitudeFt: 7400, headingDeg: 270, iasKt: 250,
      clearedAltitudeFt: 7400, clearedSpeedKt: 250, squawk: '1002',
    });
    sim.step(40);

    const violation = sim.safety.violations[0];
    expect(violation?.kind).toBe('stca');
    expect([...(violation?.callsigns ?? [])].sort()).toEqual(['AAA1', 'BBB2']);
    expect(violation?.requiredLateralNm).toBe(3);
    expect(violation?.requiredVerticalFt).toBe(1000);
    expect(violation?.actualLateralNm ?? 99).toBeLessThan(2.5);
    expect(violation?.actualVerticalFt).toBeCloseTo(400, 0);
    expect(violation?.worstAtSec).toBeGreaterThanOrEqual(violation?.startedAtSec ?? 0);
  });
});

describe('the sector at rest', () => {
  it('starts with every aircraft inside the airspace and nothing alerting', () => {
    const sim = build();
    sim.step(5);
    expect(sim.safety.alerts).toHaveLength(0);
    expect(sim.safety.violations).toHaveLength(0);
  });

  it('keeps a holding aircraft inside the sector at every entry point', () => {
    const airspace = new Airspace(airspaceData as unknown as RawAirspace);
    const entryHolds = airspace.holds.filter(
      (h) => airspace.fix(h.fix)?.type === 'boundary',
    );
    expect(entryHolds.length).toBeGreaterThan(0);

    for (const hold of entryHolds) {
      const sim = build();
      const ac = sim.aircraft[0];
      if (ac === undefined) throw new Error('no traffic');
      const fix = airspace.fix(hold.fix);
      if (fix === undefined) throw new Error(`missing ${hold.fix}`);
      sim.aircraft = [ac];
      ac.position = fix.position;
      ac.altitudeFt = 9000;
      ac.clearance.altitudeFt = 9000;
      sim.transmit(`${ac.callsign} hold at ${hold.fix} as published`);
      sim.step(60 * 8);
      expect(
        sim.safety.alerts.filter((a) => a.kind === 'sector-exit').map((a) => a.message),
      ).toEqual([]);
    }
  });

  it('publishes every boundary fix inside the boundary', () => {
    const airspace = new Airspace(airspaceData as unknown as RawAirspace);
    for (const fix of airspace.fixes.filter((f) => f.type === 'boundary')) {
      expect(pointInPolygon(fix.position, airspace.sector.boundary)).toBe(true);
    }
  });
});

/* ------------------------------------------------- speed control on final */

describe('working the spacing on final', () => {
  it('leaves an aircraft to manage its own speed if you say nothing', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST12', 12, 0, 3000, 0, 210);
    sim.transmit('TEST12 ils 29');
    expect(sim.find('TEST12')?.clearance.speedAssignedOnApproach).toBe(false);
    sim.step(120);
    // Slowing itself down without being asked.
    expect(sim.find('TEST12')?.iasKt).toBeLessThan(210);
  });

  it('holds an assigned speed on final instead', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST13', 14, 0, 3200, 0, 210);
    sim.transmit('TEST13 ils 29');
    expect(sim.transmit('TEST13 s 180 to 4')).toBeNull();
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(false);
    expect(last?.text).toMatch(/speed 180 to 4 miles/);

    const ac = sim.find('TEST13');
    expect(ac?.clearance.speedAssignedOnApproach).toBe(true);
    expect(ac?.clearance.speedReleaseDistanceNm).toBe(4);

    // Still doing what it was told at eight miles.
    for (let i = 0; i < 40; i++) {
      sim.step(5);
      const now = sim.find('TEST13');
      if (now === undefined) break;
      const runway = sim.airspace.runway('29');
      if (runway === undefined) break;
      const range = -alongTrackNm(now.position, runway.threshold, runway.trueHeadingDeg);
      if (range < 8) break;
    }
    expect(sim.find('TEST13')?.iasKt).toBeCloseTo(180, 0);
  });

  it('releases the speed at the distance named, and lands', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST14', 14, 0, 3200, 0, 200);
    sim.transmit('TEST14 ils 29');
    sim.transmit('TEST14 s 180 to 4');
    for (let i = 0; i < 200 && sim.find('TEST14') !== undefined; i++) sim.step(5);
    expect(sim.arrivals).toBe(1);
    expect(sim.goArounds).toBe(0);
  });

  it('sends one around if you hold it fast all the way in', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST15', 14, 0, 3200, 0, 250);
    sim.transmit('TEST15 ils 29');
    sim.transmit('TEST15 s 250 to 2');
    for (let i = 0; i < 200 && sim.goArounds === 0 && sim.arrivals === 0; i++) sim.step(5);
    expect(sim.goArounds).toBe(1);
    expect(sim.arrivals).toBe(0);
    expect(sim.comms.some((c) => /too fast to be stable/.test(c.text))).toBe(true);
  });

  it('takes minimum approach speed', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST16', 12, 0, 3000, 0, 200);
    sim.transmit('TEST16 ils 29');
    expect(sim.transmit('TEST16 reduce to minimum approach speed')).toBeNull();
    const ac = sim.find('TEST16');
    expect(ac?.clearance.speedKt).toBe(ac?.profile.speeds.approachIasKt);
    expect(ac?.clearance.speedReleaseDistanceNm).toBe(0);
    expect(sim.comms[sim.comms.length - 1]?.text).toMatch(/minimum approach speed, 138 knots/);
  });

  it('refuses minimum approach speed to something not on an approach', () => {
    const sim = build();
    sim.transmit('AIC101 min');
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(true);
    expect(last?.text).toMatch(/not on an approach/);
  });

  it('refuses a held speed to something not on an approach', () => {
    const sim = build();
    // Inside the A320's envelope, so the refusal is about the hold, not the speed.
    sim.transmit('AIC101 s 240 to 5');
    const last = sim.comms[sim.comms.length - 1];
    expect(last?.rejected).toBe(true);
    expect(last?.text).toMatch(/nothing to hold that speed to/);
  });

  it('hands speed back to the crew when the approach is cleared again', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST17', 14, 0, 3200, 0, 210);
    sim.transmit('TEST17 ils 29');
    sim.transmit('TEST17 s 180 to 4');
    expect(sim.find('TEST17')?.clearance.speedAssignedOnApproach).toBe(true);
    sim.transmit('TEST17 ils 29');
    expect(sim.find('TEST17')?.clearance.speedAssignedOnApproach).toBe(false);
  });

  it('drops the assignment when the aircraft leaves the approach', () => {
    const sim = build();
    sim.aircraft = [];
    placeOnFinal(sim, 'TEST18', 12, 0, 3000, 0, 200);
    sim.transmit('TEST18 ils 29');
    sim.transmit('TEST18 s 180');
    expect(sim.find('TEST18')?.clearance.speedAssignedOnApproach).toBe(true);
    sim.transmit('TEST18 fh 180');
    expect(sim.find('TEST18')?.clearance.speedAssignedOnApproach).toBe(false);
  });
});
