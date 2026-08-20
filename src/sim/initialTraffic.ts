/**
 * Milestone 1 traffic.
 *
 * Four aircraft placed by hand so the scope, the data blocks and every
 * command can be exercised immediately. Milestone 5 replaces this with the
 * scenario files; the seeding interface it uses is already the one here.
 */

import { Point, bearingDeg, movePoint } from './geo.js';
import { Simulation } from './world.js';

interface Placement {
  readonly callsign: string;
  readonly type: string;
  readonly wake: 'L' | 'M' | 'H' | 'J';
  /** Fix to place the aircraft near. */
  readonly atFix: string;
  /** Nautical miles beyond that fix, along the outbound radial from the field. */
  readonly beyondNm: number;
  readonly altitudeFt: number;
  readonly clearedAltitudeFt: number;
  readonly iasKt: number;
  readonly clearedSpeedKt: number;
  readonly squawk: string;
  readonly route: readonly string[];
  /** When set the aircraft flies this magnetic heading instead of a route. */
  readonly headingDeg?: number;
}

const PLACEMENTS: readonly Placement[] = [
  {
    callsign: 'AIC101', type: 'A320', wake: 'M', atFix: 'GUDUR', beyondNm: 2,
    altitudeFt: 11000, clearedAltitudeFt: 9000, iasKt: 290, clearedSpeedKt: 280,
    squawk: '4271', route: ['TUMSA', 'SAHIB'],
  },
  {
    callsign: 'IGO2145', type: 'B738', wake: 'M', atFix: 'NOMAN', beyondNm: 2,
    altitudeFt: 10000, clearedAltitudeFt: 8000, iasKt: 280, clearedSpeedKt: 250,
    squawk: '4302', route: ['ROHTA', 'DAULA'],
  },
  {
    callsign: 'VTI872', type: 'B77W', wake: 'H', atFix: 'BUXOR', beyondNm: 2,
    altitudeFt: 13000, clearedAltitudeFt: 11000, iasKt: 300, clearedSpeedKt: 280,
    squawk: '4415', route: ['ALGAN', 'DAULA'],
  },
  {
    callsign: 'SEJ301', type: 'Q400', wake: 'M', atFix: 'SOKAT', beyondNm: 0,
    altitudeFt: 7000, clearedAltitudeFt: 7000, iasKt: 220, clearedSpeedKt: 220,
    squawk: '4520', route: [], headingDeg: 340,
  },
];

export function seedMilestoneOneTraffic(sim: Simulation): void {
  const field: Point = { x: 0, y: 0 };

  for (const p of PLACEMENTS) {
    const fix = sim.airspace.fix(p.atFix);
    if (fix === undefined) throw new Error(`initial traffic references unknown fix ${p.atFix}`);

    const outbound = bearingDeg(field, fix.position);
    const position = movePoint(fix.position, outbound, p.beyondNm);
    const inboundTrue = bearingDeg(position, field);
    const inboundMagnetic = sim.airspace.toMagnetic(inboundTrue);

    const route = [...p.route];
    const directFix = route.shift();

    sim.add({
      callsign: p.callsign,
      type: p.type,
      wake: p.wake,
      role: 'arrival',
      position,
      altitudeFt: p.altitudeFt,
      headingDeg: p.headingDeg ?? inboundMagnetic,
      iasKt: p.iasKt,
      clearedAltitudeFt: p.clearedAltitudeFt,
      clearedSpeedKt: p.clearedSpeedKt,
      squawk: p.squawk,
      route,
      ...(p.headingDeg === undefined && directFix !== undefined ? { directFix } : {}),
    });
  }

  sim.say('system', null, `${sim.airspace.sector.name} — ${PLACEMENTS.length} aircraft on frequency.`, false);
}
