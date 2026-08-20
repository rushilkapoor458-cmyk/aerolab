/**
 * The simulation. Pure logic: it never touches the DOM and never reads a
 * clock of its own, so a test can drive it a step at a time.
 */

import { Airspace } from './airspace.js';
import { Point, angleDiff, distanceNm, normalizeDeg, pointInPolygon } from './geo.js';
import { RADAR_SWEEP_SEC, Wind } from './flight.js';
import { stepAircraft } from './flight.js';
import { updateAutoflight } from './autoflight.js';
import { updateFuel } from './fuel.js';
import { PerformanceCatalogue } from './performance.js';
import { Rng } from './rng.js';
import { Weather, defaultWeather, windAtAltitude } from './weather.js';
import { Aircraft, Clearance, CommsEntry, FlightRole } from './types.js';
import { parseCommandLine } from './commands/parser.js';
import { executeCommands } from './commands/execute.js';

/** Largest integration step the flight model is advanced by. */
const MAX_SUBSTEP_SEC = 0.25;

export interface AircraftSeed {
  readonly callsign: string;
  /** ICAO type designator; must have a profile in `aircraft.json`. */
  readonly type: string;
  readonly role: FlightRole;
  readonly position: Point;
  readonly altitudeFt: number;
  readonly headingDeg: number;
  readonly iasKt: number;
  readonly clearedAltitudeFt: number;
  readonly clearedSpeedKt: number;
  readonly squawk: string;
  readonly route?: readonly string[];
  readonly directFix?: string;
  /** All-up mass. Defaults to the profile's reference mass. */
  readonly massKg?: number;
  /** Fuel on board. Defaults to the profile's typical arrival fuel. */
  readonly fuelKg?: number;
}

export interface RunwayConfiguration {
  readonly arrival: string;
  readonly departure: string;
}

export class Simulation {
  readonly airspace: Airspace;
  readonly performance: PerformanceCatalogue;
  readonly rng: Rng;
  weather: Weather;
  aircraft: Aircraft[] = [];
  /** Seconds since midnight UTC. */
  timeSec: number;
  comms: CommsEntry[] = [];
  runways: RunwayConfiguration;

  private nextCommsId = 1;
  private nextAircraftId = 1;

  constructor(
    airspace: Airspace,
    performance: PerformanceCatalogue,
    seed: number,
    startTimeSec = 10 * 3600 + 12 * 60,
  ) {
    this.airspace = airspace;
    this.performance = performance;
    this.rng = new Rng(seed);
    this.weather = defaultWeather();
    this.timeSec = startTimeSec;
    this.runways = this.suggestedRunways();
  }

  /** Surface wind as the flight model needs it: FROM, in true degrees. */
  get wind(): Wind {
    return this.windAt(this.airspace.airport.elevationFt);
  }

  /**
   * The wind at an altitude, in the form the flight model wants. The weather
   * stores magnetic directions because that is what the ATIS reads out.
   */
  windAt(altitudeFt: number): Wind {
    const vector = windAtAltitude(this.weather, altitudeFt, this.airspace.airport.elevationFt);
    return {
      fromTrueDeg: normalizeDeg(vector.directionDeg + this.airspace.airport.magneticVariationDeg),
      speedKt: vector.speedKt,
    };
  }

  /**
   * The runway pair with the most headwind. Landing into wind is the whole
   * of runway selection at this level of detail.
   */
  suggestedRunways(): RunwayConfiguration {
    let best: string | null = null;
    let bestHeadwind = -Infinity;
    for (const runway of this.airspace.runways) {
      const off = angleDiff(runway.magneticHeadingDeg, this.weather.windDirectionDeg);
      const headwind = this.weather.windSpeedKt * Math.cos((off * Math.PI) / 180);
      if (headwind > bestHeadwind) {
        bestHeadwind = headwind;
        best = runway.ident;
      }
    }
    const arrival = best ?? this.airspace.runways[0]?.ident ?? '';
    return { arrival, departure: arrival };
  }

  add(seed: AircraftSeed): Aircraft {
    const profile = this.performance.require(seed.type);
    const clearance: Clearance = {
      headingDeg: seed.headingDeg,
      turn: 'shortest',
      turnRemainingDeg: null,
      altitudeFt: seed.clearedAltitudeFt,
      speedKt: seed.clearedSpeedKt,
      directFix: seed.directFix ?? null,
      lateralMode: seed.directFix === undefined ? 'heading' : 'direct',
      speedRestrictionCancelled: false,
      expedite: false,
    };
    const aircraft: Aircraft = {
      id: `ac${this.nextAircraftId++}`,
      callsign: seed.callsign,
      type: profile.icao,
      profile,
      wake: profile.wake,
      role: seed.role,
      position: seed.position,
      altitudeFt: seed.altitudeFt,
      headingDeg: normalizeDeg(seed.headingDeg),
      trueTrackDeg: normalizeDeg(seed.headingDeg + this.airspace.airport.magneticVariationDeg),
      iasKt: seed.iasKt,
      groundspeedKt: seed.iasKt,
      bankDeg: 0,
      verticalSpeedFpm: 0,
      squawk: seed.squawk,
      massKg: seed.massKg ?? profile.mass.referenceKg,
      fuelKg: seed.fuelKg ?? profile.typicalArrivalFuelKg,
      fuelState: 'normal',
      clearance,
      route: seed.route === undefined ? [] : [...seed.route],
      phase: 'cruise',
      history: [seed.position],
      sweepTimerSec: RADAR_SWEEP_SEC,
      handedOff: false,
      handedOffTo: null,
      handedOffFrequencyMhz: null,
    };
    this.aircraft.push(aircraft);
    return aircraft;
  }

  find(callsign: string): Aircraft | undefined {
    const wanted = callsign.toUpperCase();
    return this.aircraft.find((a) => a.callsign === wanted);
  }

  /** Advance the world. `dtSec` is simulated seconds, already rate-scaled. */
  step(dtSec: number): void {
    let remaining = dtSec;
    const ctx = {
      windAt: (altitudeFt: number): Wind => this.windAt(altitudeFt),
      magneticVariationDeg: this.airspace.airport.magneticVariationDeg,
    };
    const elevation = this.airspace.airport.elevationFt;

    while (remaining > 1e-6) {
      const dt = Math.min(MAX_SUBSTEP_SEC, remaining);
      remaining -= dt;
      this.timeSec += dt;
      for (const ac of this.aircraft) {
        const auto = updateAutoflight(ac, this.airspace, this.windAt(ac.altitudeFt));
        for (const report of auto.reports) this.say('pilot', ac.callsign, report, false);
        stepAircraft(ac, auto.targetHeadingDeg, dt, ctx);
        for (const call of updateFuel(ac, dt, elevation)) {
          this.say('pilot', ac.callsign, call, ac.fuelState === 'emergency');
        }
      }
      this.retireDepartedAircraft();
    }
  }

  /**
   * An aircraft that has been handed off and has left the sector is no longer
   * this position's problem, and drops off the display.
   */
  private retireDepartedAircraft(): void {
    for (let i = this.aircraft.length - 1; i >= 0; i--) {
      const ac = this.aircraft[i];
      if (ac === undefined || !ac.handedOff) continue;
      if (pointInPolygon(ac.position, this.airspace.sector.boundary)) continue;
      this.aircraft.splice(i, 1);
      this.say('system', ac.callsign, `${ac.callsign} has left the sector.`, false);
    }
  }

  /**
   * Handle one line typed into the command bar. Returns the parse error, if
   * any, so the command bar can keep the text for correction.
   */
  transmit(line: string): string | null {
    const parsed = parseCommandLine(line);
    if (!parsed.ok) {
      this.say('system', null, parsed.error, true);
      return parsed.error;
    }
    const ac = this.find(parsed.value.callsign);
    if (ac === undefined) {
      const error = `No aircraft ${parsed.value.callsign} on this frequency.`;
      this.say('system', null, error, true);
      return error;
    }
    if (ac.handedOff) {
      const error = `${ac.callsign} is no longer on this frequency — handed to ${ac.handedOffTo ?? 'another sector'}.`;
      this.say('system', null, error, true);
      return error;
    }
    this.say('atc', ac.callsign, `${ac.callsign}, ${describe(line)}`, false);
    const outcome = executeCommands(ac, parsed.value.commands, this.airspace);
    this.say('pilot', ac.callsign, outcome.readback, outcome.rejected);
    return null;
  }

  /** Append a line to the comms panel. */
  say(source: CommsEntry['source'], callsign: string | null, text: string, rejected: boolean): void {
    this.comms.push({
      id: this.nextCommsId++,
      timeSec: this.timeSec,
      source,
      callsign,
      text,
      rejected,
    });
    // The panel only ever shows the tail; keeping the whole session would
    // grow without bound over a long shift.
    if (this.comms.length > 400) this.comms.splice(0, this.comms.length - 400);
  }

  /** Range and bearing between two points, for the scope's measuring tool. */
  measure(from: Point, to: Point): { rangeNm: number; bearingMagneticDeg: number } {
    const rangeNm = distanceNm(from, to);
    const trueBearing = normalizeDeg(
      (Math.atan2(to.x - from.x, to.y - from.y) * 180) / Math.PI,
    );
    return { rangeNm, bearingMagneticDeg: this.airspace.toMagnetic(trueBearing) };
  }
}

/** Echo the controller's own transmission back into the log, tidied up. */
function describe(line: string): string {
  const tokens = line.trim().split(/\s+/);
  return tokens.slice(1).join(' ').toLowerCase();
}
