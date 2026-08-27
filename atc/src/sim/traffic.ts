/**
 * The traffic director: generates the aircraft a scenario asks for.
 *
 * Every choice — type, airline, entry fix, level, fuel, and the interval to
 * the next one — comes from the scenario's own random stream, so a seed
 * reproduces a session exactly.
 */

import { Airspace, Star } from './airspace.js';
import { bearingDeg, movePoint } from './geo.js';
import { placeAtHoldingPoint } from './departure.js';
import { Rng } from './rng.js';
import { AirlineEntry, FleetEntry, Range, Scenario } from './scenario.js';
import { Aircraft } from './types.js';
import { Simulation } from './world.js';

/** How far inside its entry fix an arrival appears. */
export const ARRIVAL_ENTRY_OFFSET_NM = 2;
/** Departures never queue deeper than this; beyond it the flow simply waits. */
export const MAX_DEPARTURE_QUEUE = 6;

export class TrafficDirector {
  private readonly rng: Rng;
  private nextArrivalSec: number;
  private nextDepartureSec: number;
  private sidIndex = 0;
  private readonly used = new Set<string>();

  constructor(
    private readonly scenario: Scenario,
    seed: number,
    startTimeSec: number,
  ) {
    this.rng = new Rng(seed);
    // Neither stream starts at zero, or the session opens with a burst.
    this.nextArrivalSec = startTimeSec + this.arrivalInterval() * this.rng.range(0.2, 0.8);
    this.nextDepartureSec = startTimeSec + this.departureInterval() * this.rng.range(0.2, 0.8);
  }

  private arrivalInterval(): number {
    const perHour = this.scenario.traffic.arrivalsPerHour;
    return perHour <= 0 ? Infinity : 3600 / perHour;
  }

  private departureInterval(): number {
    const perHour = this.scenario.traffic.departuresPerHour;
    return perHour <= 0 ? Infinity : 3600 / perHour;
  }

  /** Generate whatever is due by `timeSec`. */
  update(sim: Simulation, timeSec: number): void {
    while (timeSec >= this.nextArrivalSec) {
      this.spawnArrival(sim);
      // Jitter the interval so the stream is not metronomic.
      this.nextArrivalSec += this.arrivalInterval() * this.rng.range(0.7, 1.3);
    }
    while (timeSec >= this.nextDepartureSec) {
      if (this.queueDepth(sim) < MAX_DEPARTURE_QUEUE) this.spawnDeparture(sim);
      this.nextDepartureSec += this.departureInterval() * this.rng.range(0.7, 1.3);
    }
  }

  private queueDepth(sim: Simulation): number {
    return sim.aircraft.filter((ac) => ac.ground === 'queue' || ac.ground === 'lineup').length;
  }

  /* --------------------------------------------------------------- spawning */

  /** An arrival at one of the scenario's entry fixes, on the STAR from it. */
  spawnArrival(sim: Simulation, overrides: Partial<ArrivalSpec> = {}): Aircraft | null {
    const traffic = this.scenario.traffic;
    const fixName = overrides.entryFix ?? pickWeighted(this.rng, traffic.entryFixes.map((f) => ({ value: f, weight: 1 })));
    if (fixName === null) return null;

    const fix = sim.airspace.fix(fixName);
    const star = starFrom(sim.airspace, fixName);
    if (fix === undefined || star === undefined) return null;

    const type = overrides.type ?? pickFleet(this.rng, traffic.fleet);
    if (type === null) return null;
    const profile = sim.performance.get(type);
    if (profile === undefined) return null;

    const callsign = overrides.callsign ?? this.nextCallsign(traffic.airlines);
    const altitude =
      overrides.altitudeFt ?? roundTo(pickRange(this.rng, traffic.entryAltitudeFt), 1000);
    const speed = overrides.speedKt ?? traffic.entrySpeedKt;

    // Just inside the fix, tracking towards the field.
    const outbound = bearingDeg({ x: 0, y: 0 }, fix.position);
    const position = movePoint(fix.position, outbound, ARRIVAL_ENTRY_OFFSET_NM);
    const route = star.legs.map((leg) => leg.fix).filter((name) => name !== fix.name);
    const directFix = route.shift();

    const fuel =
      overrides.fuelKg ?? profile.typicalArrivalFuelKg * pickRange(this.rng, traffic.fuelFactor);

    return sim.add({
      callsign,
      type: profile.icao,
      role: 'arrival',
      position,
      altitudeFt: altitude,
      headingDeg: sim.airspace.toMagnetic(bearingDeg(position, fix.position)),
      iasKt: Math.min(speed, profile.speeds.maxIasKt),
      clearedAltitudeFt: altitude,
      clearedSpeedKt: Math.min(speed, profile.speeds.maxIasKt),
      squawk: this.nextSquawk(),
      route,
      procedure: star.ident,
      fuelKg: fuel,
      ...(directFix === undefined ? {} : { directFix }),
    });
  }

  /** A departure at the holding point, ready for its clearance. */
  spawnDeparture(sim: Simulation, overrides: Partial<DepartureSpec> = {}): Aircraft | null {
    const traffic = this.scenario.traffic;
    const type = overrides.type ?? pickFleet(this.rng, traffic.fleet);
    if (type === null) return null;
    const profile = sim.performance.get(type);
    if (profile === undefined) return null;

    const runway = sim.airspace.runway(sim.runways.departure);
    if (runway === undefined) return null;

    const sidIdent = overrides.sid ?? this.nextSid(sim);
    const sid = sidIdent === null ? undefined : sim.airspace.sid(sidIdent);
    const legs = sid === undefined ? [] : sid.legs.map((leg) => leg.fix);
    const route = [...legs];
    const directFix = route.shift();
    const initialAltitude = sid?.legs[0]?.altitudeConstraint?.altitudeFt ?? 5000;

    const aircraft = sim.add({
      callsign: overrides.callsign ?? this.nextCallsign(traffic.airlines),
      type: profile.icao,
      role: 'departure',
      position: runway.threshold,
      altitudeFt: runway.thresholdElevationFt,
      headingDeg: runway.magneticHeadingDeg,
      iasKt: 0,
      clearedAltitudeFt: initialAltitude,
      clearedSpeedKt: profile.speeds.minCleanIasKt,
      squawk: this.nextSquawk(),
      route,
      ...(sid === undefined ? {} : { procedure: sid.ident }),
      ...(directFix === undefined ? {} : { directFix }),
    });
    placeAtHoldingPoint(aircraft, runway, sim.airspace.airport.magneticVariationDeg);
    return aircraft;
  }

  /* --------------------------------------------------------------- helpers */

  /** SIDs are issued in rotation, so departures fan out instead of trailing. */
  private nextSid(sim: Simulation): string | null {
    const usable = this.scenario.traffic.departureSids.filter((ident) => {
      const sid = sim.airspace.sid(ident);
      return sid !== undefined && sid.runways.includes(sim.runways.departure);
    });
    if (usable.length === 0) return null;
    const ident = usable[this.sidIndex % usable.length] ?? null;
    this.sidIndex += 1;
    return ident;
  }

  private nextCallsign(airlines: readonly AirlineEntry[]): string {
    for (let attempt = 0; attempt < 200; attempt++) {
      const airline = pickWeighted(
        this.rng,
        airlines.map((a) => ({ value: a, weight: a.weight })),
      );
      const prefix = airline?.prefix ?? 'XXX';
      const callsign = `${prefix}${this.rng.int(100, 999)}`;
      if (!this.used.has(callsign)) {
        this.used.add(callsign);
        return callsign;
      }
    }
    // Every reasonable combination taken: fall back to something unique.
    const fallback = `ZZZ${this.used.size}`;
    this.used.add(fallback);
    return fallback;
  }

  /** A discrete code, avoiding the reserved emergency ones. */
  private nextSquawk(): string {
    for (let attempt = 0; attempt < 200; attempt++) {
      const code = `${this.rng.int(1, 6)}${this.rng.int(0, 7)}${this.rng.int(0, 7)}${this.rng.int(0, 7)}`;
      if (code !== '7700' && code !== '7600' && code !== '7500') return code;
    }
    return '2000';
  }
}

export interface ArrivalSpec {
  callsign: string;
  type: string;
  entryFix: string;
  altitudeFt: number;
  speedKt: number;
  fuelKg: number;
}

export interface DepartureSpec {
  callsign: string;
  type: string;
  sid: string;
}

/** The STAR that begins at a given boundary fix. */
export function starFrom(airspace: Airspace, fixName: string): Star | undefined {
  const wanted = fixName.toUpperCase();
  return airspace.stars.find((star) => star.boundaryFix.toUpperCase() === wanted);
}

function pickFleet(rng: Rng, fleet: readonly FleetEntry[]): string | null {
  const entry = pickWeighted(rng, fleet.map((f) => ({ value: f.type, weight: f.weight })));
  return entry;
}

function pickWeighted<T>(rng: Rng, entries: readonly { value: T; weight: number }[]): T | null {
  const total = entries.reduce((sum, e) => sum + Math.max(0, e.weight), 0);
  if (total <= 0) return null;
  let roll = rng.range(0, total);
  for (const entry of entries) {
    roll -= Math.max(0, entry.weight);
    if (roll <= 0) return entry.value;
  }
  return entries[entries.length - 1]?.value ?? null;
}

function pickRange(rng: Rng, range: Range): number {
  return rng.range(range.min, range.max);
}

function roundTo(value: number, step: number): number {
  return Math.round(value / step) * step;
}
