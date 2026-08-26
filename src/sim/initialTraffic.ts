/**
 * Hand-placed starting traffic.
 *
 * Six aircraft spanning the whole performance range — a 777 and an A350 down
 * to a Cessna — so the scope, the data blocks and every command can be
 * exercised immediately. SEJ301 is deliberately short of fuel, so if you leave
 * it alone it will advise minimum fuel and then declare an emergency.
 *
 * Milestone 5 replaces this with the scenario files; the seeding interface it
 * uses is already the one here.
 */

import { Point, bearingDeg, movePoint } from './geo.js';
import { Simulation } from './world.js';

interface Placement {
  readonly callsign: string;
  /** ICAO type designator; the wake category comes from its profile. */
  readonly type: string;
  /** Fix to place the aircraft near. */
  readonly atFix: string;
  /**
   * Nautical miles beyond that fix along the outbound radial from the field.
   * Negative places the aircraft inside it, which is where traffic that has
   * just entered the sector actually is.
   */
  readonly beyondNm: number;
  readonly altitudeFt: number;
  readonly clearedAltitudeFt: number;
  readonly iasKt: number;
  readonly clearedSpeedKt: number;
  readonly squawk: string;
  readonly route: readonly string[];
  /** Published STAR the route comes from. */
  readonly procedure?: string;
  /** When set the aircraft flies this magnetic heading instead of a route. */
  readonly headingDeg?: number;
  /** Fuel on board. Defaults to the profile's typical arrival figure. */
  readonly fuelKg?: number;
  /** All-up mass. Defaults to the profile's reference mass. */
  readonly massKg?: number;
}

const PLACEMENTS: readonly Placement[] = [
  {
    callsign: 'AIC101', type: 'A320', atFix: 'GUDUR', beyondNm: -2,
    altitudeFt: 11000, clearedAltitudeFt: 9000, iasKt: 290, clearedSpeedKt: 280,
    squawk: '4271', route: ['TUMSA', 'SAHIB'], procedure: 'GUDUR1A',
  },
  {
    callsign: 'IGO2145', type: 'B738', atFix: 'NOMAN', beyondNm: -2,
    altitudeFt: 10000, clearedAltitudeFt: 8000, iasKt: 280, clearedSpeedKt: 250,
    squawk: '4302', route: ['ROHTA', 'DAULA'], procedure: 'NOMAN1H',
  },
  {
    callsign: 'VTI872', type: 'B77W', atFix: 'BUXOR', beyondNm: -2,
    altitudeFt: 13000, clearedAltitudeFt: 11000, iasKt: 300, clearedSpeedKt: 280,
    squawk: '4415', route: ['ALGAN', 'DAULA'], procedure: 'BUXOR1J',
  },
  {
    callsign: 'SEJ301', type: 'Q400', atFix: 'SOKAT', beyondNm: 0,
    altitudeFt: 7000, clearedAltitudeFt: 7000, iasKt: 220, clearedSpeedKt: 220,
    // About thirty-five minutes of fuel: it will call minimum fuel before long.
    squawk: '4520', route: [], headingDeg: 340, fuelKg: 520,
  },
  {
    callsign: 'QTR578', type: 'A359', atFix: 'RAKMO', beyondNm: -2,
    altitudeFt: 14000, clearedAltitudeFt: 12000, iasKt: 300, clearedSpeedKt: 290,
    squawk: '4633', route: ['KIRAN', 'DAULA'], procedure: 'RAKMO1C', massKg: 215000,
  },
  {
    callsign: 'VTABC', type: 'C172', atFix: 'SITAX', beyondNm: -8,
    altitudeFt: 4500, clearedAltitudeFt: 4500, iasKt: 105, clearedSpeedKt: 105,
    squawk: '4701', route: [], headingDeg: 20,
  },
];

export function seedInitialTraffic(sim: Simulation): void {
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
      role: 'arrival',
      position,
      altitudeFt: p.altitudeFt,
      headingDeg: p.headingDeg ?? inboundMagnetic,
      iasKt: p.iasKt,
      clearedAltitudeFt: p.clearedAltitudeFt,
      clearedSpeedKt: p.clearedSpeedKt,
      squawk: p.squawk,
      route,
      ...(p.procedure === undefined ? {} : { procedure: p.procedure }),
      ...(p.fuelKg === undefined ? {} : { fuelKg: p.fuelKg }),
      ...(p.massKg === undefined ? {} : { massKg: p.massKg }),
      ...(p.headingDeg === undefined && directFix !== undefined ? { directFix } : {}),
    });
  }

  sim.say('system', null, `${sim.airspace.sector.name} — ${PLACEMENTS.length} aircraft on frequency.`, false);
}
