/**
 * Scenario files: what traffic to generate, in what weather, and what happens
 * during the session.
 *
 * A scenario is data. Everything it can ask for is something the simulation
 * already does — there is no scripting language here, only a list of events
 * with times against them.
 */

import { Airspace } from './airspace.js';
import { Point, bearingDeg, movePoint, pointInPolygon } from './geo.js';
import { PerformanceCatalogue } from './performance.js';
import { Weather } from './weather.js';

export interface FleetEntry {
  readonly type: string;
  /** Relative likelihood of being picked. */
  readonly weight: number;
}

export interface AirlineEntry {
  /** ICAO three letter prefix, e.g. AIC. */
  readonly prefix: string;
  readonly name: string;
  readonly weight: number;
}

export interface Range {
  readonly min: number;
  readonly max: number;
}

export interface ScenarioTraffic {
  readonly arrivalsPerHour: number;
  readonly departuresPerHour: number;
  readonly fleet: readonly FleetEntry[];
  readonly airlines: readonly AirlineEntry[];
  /** Sector entry fixes arrivals appear at. Each must have a STAR. */
  readonly entryFixes: readonly string[];
  readonly entryAltitudeFt: Range;
  readonly entrySpeedKt: number;
  /** Fuel on arrival as a fraction of the type's typical figure. */
  readonly fuelFactor: Range;
  /** SIDs departures are issued, in rotation. */
  readonly departureSids: readonly string[];
}

export type EmergencyKind = 'engine' | 'radio';

export type ScenarioEvent =
  | { readonly atMin: number; readonly kind: 'message'; readonly text: string }
  | { readonly atMin: number; readonly kind: 'weather'; readonly weather: Partial<Weather> }
  | {
      readonly atMin: number;
      readonly kind: 'runway-change';
      readonly arrival: string;
      readonly departure: string;
    }
  | {
      readonly atMin: number;
      readonly kind: 'emergency';
      readonly emergency: EmergencyKind;
      /** Which aircraft it happens to. */
      readonly target: 'random-arrival' | 'random-departure';
    }
  | {
      readonly atMin: number;
      readonly kind: 'arrival';
      readonly callsign: string;
      readonly type: string;
      readonly entryFix: string;
      readonly altitudeFt: number;
      readonly speedKt: number;
      readonly fuelKg?: number;
    }
  | {
      readonly atMin: number;
      readonly kind: 'departure';
      readonly callsign: string;
      readonly type: string;
      readonly sid: string;
    };

/**
 * An aircraft already airborne when the session opens.
 *
 * A scenario that starts on an empty scope makes you wait several minutes for
 * anything to control. These place traffic in the sector at t=0, positioned
 * relative to a published fix so the picture is legal: on a STAR, inside the
 * boundary, at a plausible level for its distance.
 */
export interface InitialAircraft {
  readonly callsign: string;
  /** ICAO type designator; the wake category comes from its profile. */
  readonly type: string;
  /** Fix to place it near. */
  readonly atFix: string;
  /**
   * Nautical miles beyond that fix along the outbound radial from the field.
   * Negative places it inside the fix, which is where traffic that entered a
   * few minutes ago actually is.
   */
  readonly beyondNm: number;
  readonly altitudeFt: number;
  readonly clearedAltitudeFt: number;
  readonly iasKt: number;
  readonly clearedSpeedKt: number;
  readonly squawk: string;
  /** Remaining route after the fix it is tracking to. */
  readonly route: readonly string[];
  /** Published STAR the route came from. */
  readonly procedure?: string;
  /** When set it flies this magnetic heading instead of tracking a route. */
  readonly headingDeg?: number;
  readonly fuelKg?: number;
  readonly massKg?: number;
}

export interface Scenario {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly seed: number;
  /** Session start, `HH:MM` UTC. */
  readonly startTimeUtc: string;
  readonly durationMin: number;
  readonly runways: { readonly arrival: string; readonly departure: string };
  readonly traffic: ScenarioTraffic;
  /** Traffic already on frequency when the session opens. */
  readonly initialTraffic: readonly InitialAircraft[];
  readonly weather: Weather;
  readonly events: readonly ScenarioEvent[];
}

/** Seconds since midnight for a scenario's `HH:MM` start time. */
export function startTimeSec(scenario: Scenario): number {
  const match = /^(\d{2}):(\d{2})$/.exec(scenario.startTimeUtc);
  if (match === null) {
    throw new Error(`scenario ${scenario.id} has a bad startTimeUtc "${scenario.startTimeUtc}"`);
  }
  return Number(match[1]) * 3600 + Number(match[2]) * 60;
}

/**
 * Check a scenario against the airspace and the performance catalogue it will
 * run with, so a typo fails at load rather than halfway through a session.
 */
export function validateScenario(
  scenario: Scenario,
  airspace: Airspace,
  performance: PerformanceCatalogue,
): void {
  const problems: string[] = [];
  const where = `scenario ${scenario.id}`;

  startTimeSec(scenario);
  if (scenario.durationMin <= 0) problems.push(`${where} has a duration of ${scenario.durationMin}`);

  for (const ident of [scenario.runways.arrival, scenario.runways.departure]) {
    if (airspace.runway(ident) === undefined) problems.push(`${where} names unknown runway ${ident}`);
  }

  for (const entry of scenario.traffic.fleet) {
    if (performance.get(entry.type) === undefined) {
      problems.push(`${where} names unknown aircraft type ${entry.type}`);
    }
  }
  if (scenario.traffic.arrivalsPerHour > 0 && scenario.traffic.fleet.length === 0) {
    problems.push(`${where} generates arrivals but has an empty fleet`);
  }
  if (scenario.traffic.arrivalsPerHour > 0 && scenario.traffic.airlines.length === 0) {
    problems.push(`${where} generates arrivals but has no airlines`);
  }

  for (const fixName of scenario.traffic.entryFixes) {
    const fix = airspace.fix(fixName);
    if (fix === undefined) {
      problems.push(`${where} names unknown entry fix ${fixName}`);
      continue;
    }
    if (!airspace.stars.some((star) => star.boundaryFix === fix.name)) {
      problems.push(`${where} uses ${fix.name} as an entry fix but no STAR starts there`);
    }
  }

  // Traffic the scenario opens with has to be inside the sector it opens in.
  // Placing an aircraft beyond the boundary makes the safety net right to
  // complain the moment the session starts, which reads as a bug in the
  // simulator rather than in the scenario file.
  const field: Point = { x: 0, y: 0 };
  for (const placement of scenario.initialTraffic ?? []) {
    if (performance.get(placement.type) === undefined) {
      problems.push(`${where} places ${placement.callsign} as unknown type ${placement.type}`);
    }
    const fix = airspace.fix(placement.atFix);
    if (fix === undefined) {
      problems.push(`${where} places ${placement.callsign} at unknown fix ${placement.atFix}`);
      continue;
    }
    const outbound = bearingDeg(field, fix.position);
    const position = movePoint(fix.position, outbound, placement.beyondNm);
    if (!pointInPolygon(position, airspace.sector.boundary)) {
      problems.push(
        `${where} places ${placement.callsign} outside the sector ` +
          `(${placement.beyondNm} NM beyond ${placement.atFix})`,
      );
    }
    for (const fixName of placement.route) {
      if (airspace.fix(fixName) === undefined) {
        problems.push(`${where} routes ${placement.callsign} via unknown fix ${fixName}`);
      }
    }
  }

  for (const ident of scenario.traffic.departureSids) {
    if (airspace.sid(ident) === undefined) problems.push(`${where} names unknown SID ${ident}`);
  }

  for (const event of scenario.events) {
    if (event.atMin < 0) problems.push(`${where} has an event at ${event.atMin} minutes`);
    if (event.kind === 'runway-change') {
      for (const ident of [event.arrival, event.departure]) {
        if (airspace.runway(ident) === undefined) {
          problems.push(`${where} changes to unknown runway ${ident}`);
        }
      }
    }
    if (event.kind === 'arrival') {
      if (performance.get(event.type) === undefined) {
        problems.push(`${where} spawns unknown type ${event.type}`);
      }
      if (airspace.fix(event.entryFix) === undefined) {
        problems.push(`${where} spawns at unknown fix ${event.entryFix}`);
      }
    }
    if (event.kind === 'departure') {
      if (performance.get(event.type) === undefined) {
        problems.push(`${where} departs unknown type ${event.type}`);
      }
      if (airspace.sid(event.sid) === undefined) {
        problems.push(`${where} departs on unknown SID ${event.sid}`);
      }
    }
  }

  if (problems.length > 0) {
    throw new Error(`scenario is inconsistent:\n  - ${problems.join('\n  - ')}`);
  }
}
