/**
 * Scenario files: what traffic to generate, in what weather, and what happens
 * during the session.
 *
 * A scenario is data. Everything it can ask for is something the simulation
 * already does — there is no scripting language here, only a list of events
 * with times against them.
 */

import { Airspace } from './airspace.js';
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
