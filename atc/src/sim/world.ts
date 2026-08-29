/**
 * The simulation. Pure logic: it never touches the DOM and never reads a
 * clock of its own, so a test can drive it a step at a time.
 */

import { Airspace } from './airspace.js';
import { Point, angleDiff, distanceNm, normalizeDeg, pointInPolygon } from './geo.js';
import { RADAR_SWEEP_SEC, Wind } from './flight.js';
import { stepAircraft } from './flight.js';
import { NavContext, goAround, updateAutoflight } from './autoflight.js';
import { stepGroundRoll } from './departure.js';
import { declareEngineFailure, declareRadioFailure, isOutOfContact } from './emergency.js';
import { updateFuel } from './fuel.js';
import { PerformanceCatalogue } from './performance.js';
import { Rng } from './rng.js';
import { Scenario, ScenarioEvent, startTimeSec, validateScenario } from './scenario.js';
import { TrafficDirector } from './traffic.js';
import { SafetyNet } from './safety.js';
import { SessionScore, computeScore } from './score.js';
import { WakeMatrix } from './wake.js';
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
  /** Published SID or STAR the route came from. */
  readonly procedure?: string;
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
  readonly wake: WakeMatrix;
  readonly safety: SafetyNet;
  readonly rng: Rng;
  scenario: Scenario | null = null;
  private traffic: TrafficDirector | null = null;
  private pendingEvents: ScenarioEvent[] = [];
  /** Events that could not fire yet, e.g. an emergency with nobody to give it to. */
  private deferredEvents: { event: ScenarioEvent; deadlineSec: number }[] = [];
  weather: Weather;
  aircraft: Aircraft[] = [];
  /** Seconds since midnight UTC. */
  timeSec: number;
  comms: CommsEntry[] = [];
  runways: RunwayConfiguration;

  /** Runways occupied by a landing roll, keyed by ident, value is the clock. */
  private readonly runwayClearAtSec = new Map<string, number>();
  private readonly landedIds = new Set<string>();
  /** Session counters. */
  startedAtSec: number;
  arrivals = 0;
  departures = 0;
  goArounds = 0;
  fuelBurntKg = 0;
  readonly arrivalDelaysSec: number[] = [];
  /** Seconds of simulated time still owed to the safety net. */
  private safetyTimerSec = 0;

  private nextCommsId = 1;
  private nextAircraftId = 1;

  constructor(
    airspace: Airspace,
    performance: PerformanceCatalogue,
    wake: WakeMatrix,
    seed: number,
    startTimeSec = 10 * 3600 + 12 * 60,
  ) {
    this.airspace = airspace;
    this.performance = performance;
    this.wake = wake;
    this.safety = new SafetyNet(airspace, wake);
    this.rng = new Rng(seed);
    this.weather = defaultWeather();
    this.timeSec = startTimeSec;
    this.startedAtSec = startTimeSec;
    this.runways = this.suggestedRunways();
  }

  /**
   * Load a scenario: its weather, its runway configuration, its clock, and
   * the traffic generator that will feed the session.
   */
  loadScenario(scenario: Scenario): void {
    validateScenario(scenario, this.airspace, this.performance);
    this.scenario = scenario;
    this.weather = { ...scenario.weather };
    this.runways = { ...scenario.runways };
    this.timeSec = startTimeSec(scenario);
    this.startedAtSec = this.timeSec;
    this.traffic = new TrafficDirector(scenario, scenario.seed, this.timeSec);
    // Sorted here, so an event list need not be written in time order.
    this.pendingEvents = [...scenario.events].sort((a, b) => a.atMin - b.atMin);
    this.deferredEvents = [];
    this.say('system', null, `${scenario.name} — ${scenario.description}`, false);
  }

  /** Simulated seconds remaining in the scenario, or null if it has none. */
  get remainingSec(): number | null {
    if (this.scenario === null) return null;
    return Math.max(0, this.scenario.durationMin * 60 - (this.timeSec - this.startedAtSec));
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
      descendVia: false,
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
      entryTimeSec: this.timeSec,
      entryPosition: seed.position,
      massKg: seed.massKg ?? profile.mass.referenceKg,
      fuelKg: seed.fuelKg ?? profile.typicalArrivalFuelKg,
      fuelState: 'normal',
      clearance,
      route: seed.route === undefined ? [] : [...seed.route],
      procedure: seed.procedure ?? null,
      phase: 'cruise',
      hold: null,
      approach: null,
      goAroundCount: 0,
    ground: null,
    departureRunway: null,
    emergency: 'none',
    performanceFactor: 1,
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
        if (ac.ground !== null) {
          // Sitting on the ground: no navigation, and no fuel worth counting.
          this.stepOnGround(ac, dt);
          continue;
        }
        const nav: NavContext = {
          airspace: this.airspace,
          wind: this.windAt(ac.altitudeFt),
          dtSec: dt,
          timeSec: this.timeSec,
          isRunwayOccupied: (ident) => this.isRunwayOccupied(ident),
        };
        const auto = updateAutoflight(ac, nav);
        for (const report of auto.reports) {
          this.say('pilot', ac.callsign, report, auto.wentAround);
        }
        if (auto.wentAround) this.goArounds += 1;
        if (auto.landed) {
          this.recordLanding(ac);
          continue;
        }
        stepAircraft(ac, auto.command, dt, ctx);
        const fuelBefore = ac.fuelKg;
        for (const call of updateFuel(ac, dt, elevation)) {
          this.say('pilot', ac.callsign, call, ac.fuelState === 'emergency');
        }
        this.fuelBurntKg += fuelBefore - ac.fuelKg;
      }
      this.removeLandedAircraft();
      this.retireDepartedAircraft();
      this.fireDueEvents();
      this.traffic?.update(this, this.timeSec);

      // The safety net runs on its own one second cycle, independent of the
      // frame rate, so its alerts are reproducible from the seed.
      this.safetyTimerSec += dt;
      if (this.safetyTimerSec >= 1) {
        this.safetyTimerSec -= 1;
        // Aircraft still on the ground are the tower's, not ours.
        this.safety.update(this.aircraft.filter((ac) => ac.ground === null), this.timeSec);
      }
    }
  }

  /** Advance a departure that has not left the ground yet. */
  private stepOnGround(ac: Aircraft, dtSec: number): void {
    const runway = this.airspace.runway(ac.departureRunway ?? this.runways.departure);
    if (runway === undefined) return;
    const result = stepGroundRoll(ac, dtSec, {
      wind: this.windAt(ac.altitudeFt),
      magneticVariationDeg: this.airspace.airport.magneticVariationDeg,
      runway,
    });
    if (result.airborne) {
      this.runwayClearAtSec.set(runway.ident.toUpperCase(), this.timeSec + 20);
      this.say('pilot', ac.callsign, `airborne, ${ac.callsign}`, false);
    }
  }

  /* ------------------------------------------------------------- scenario */

  /** How long a scenario keeps trying to place an emergency before giving up. */
  static readonly EVENT_DEFERRAL_SEC = 20 * 60;

  private fireDueEvents(): void {
    if (this.scenario === null) return;

    while (this.pendingEvents.length > 0) {
      const event = this.pendingEvents[0];
      if (event === undefined) break;
      if (this.timeSec - this.startedAtSec < event.atMin * 60) break;
      this.pendingEvents.shift();
      if (!this.applyEvent(event)) {
        // Nothing to give it to yet — an emergency needs an aeroplane.
        this.deferredEvents.push({
          event,
          deadlineSec: this.timeSec + Simulation.EVENT_DEFERRAL_SEC,
        });
      }
    }

    if (this.deferredEvents.length === 0) return;
    this.deferredEvents = this.deferredEvents.filter((deferred) => {
      if (this.applyEvent(deferred.event)) return false;
      if (this.timeSec < deferred.deadlineSec) return true;
      this.say('system', null, 'A scripted event was dropped: no suitable aircraft for it.', false);
      return false;
    });
  }

  /** Apply one event. Returns false if it could not be applied yet. */
  private applyEvent(event: ScenarioEvent): boolean {
    switch (event.kind) {
      case 'message':
        this.say('system', null, event.text, false);
        return true;

      case 'weather': {
        this.weather = { ...this.weather, ...event.weather };
        this.weather.atisLetter = nextAtisLetter(this.weather.atisLetter);
        const suggested = this.suggestedRunways();
        const note =
          suggested.arrival === this.runways.arrival
            ? ''
            : ` — this wind favours runway ${suggested.arrival}`;
        this.say(
          'system',
          null,
          `New ATIS, information ${this.weather.atisLetter}${note}.`,
          suggested.arrival !== this.runways.arrival,
        );
        return true;
      }

      case 'runway-change': {
        this.runways = { arrival: event.arrival, departure: event.departure };
        this.say(
          'system',
          null,
          `Runway change: arrivals runway ${event.arrival}, departures runway ${event.departure}.`,
          true,
        );
        return true;
      }

      case 'emergency': {
        const target = this.pickEmergencyTarget(event.target);
        if (target === null) return false;
        const call =
          event.emergency === 'engine' ? declareEngineFailure(target) : declareRadioFailure(target);
        this.say(event.emergency === 'engine' ? 'pilot' : 'system', target.callsign, call, true);
        return true;
      }

      case 'arrival': {
        const spec = {
          callsign: event.callsign,
          type: event.type,
          entryFix: event.entryFix,
          altitudeFt: event.altitudeFt,
          speedKt: event.speedKt,
          ...(event.fuelKg === undefined ? {} : { fuelKg: event.fuelKg }),
        };
        this.traffic?.spawnArrival(this, spec);
        return true;
      }

      case 'departure': {
        this.traffic?.spawnDeparture(this, {
          callsign: event.callsign,
          type: event.type,
          sid: event.sid,
        });
        return true;
      }

      default: {
        const unreachable: never = event;
        throw new Error(`unknown scenario event ${JSON.stringify(unreachable)}`);
      }
    }
  }

  /** Pick an aircraft for a scripted emergency, deterministically. */
  private pickEmergencyTarget(target: 'random-arrival' | 'random-departure'): Aircraft | null {
    const wanted = target === 'random-arrival' ? 'arrival' : 'departure';
    const airborne = this.aircraft.filter(
      (ac) => ac.ground === null && ac.emergency === 'none' && !ac.handedOff,
    );
    const candidates = airborne.filter((ac) => ac.role === wanted);
    if (candidates.length === 0) return null;
    return candidates[this.rng.int(0, candidates.length - 1)] ?? null;
  }

  /** True while a landing roll is still on the runway. */
  isRunwayOccupied(ident: string): boolean {
    const clearAt = this.runwayClearAtSec.get(ident.toUpperCase());
    return clearAt !== undefined && this.timeSec < clearAt;
  }

  /** Reserve a runway for a period, e.g. while a departure is on it. */
  occupyRunway(ident: string, seconds: number): void {
    this.runwayClearAtSec.set(ident.toUpperCase(), this.timeSec + seconds);
  }

  /** How long a landing aircraft keeps the runway, in seconds. */
  static readonly RUNWAY_OCCUPANCY_SEC = 55;

  private recordLanding(ac: Aircraft): void {
    const runwayIdent = ac.approach?.runway ?? this.runways.arrival;
    this.runwayClearAtSec.set(
      runwayIdent.toUpperCase(),
      this.timeSec + Simulation.RUNWAY_OCCUPANCY_SEC,
    );
    this.landedIds.add(ac.id);
    this.arrivals += 1;
    this.arrivalDelaysSec.push(this.delayForArrival(ac, runwayIdent));
    this.say('system', ac.callsign, `${ac.callsign} landed runway ${runwayIdent}.`, false);
  }

  /**
   * How much longer the aircraft took than a straight run from where it came
   * on frequency to the threshold at its own normal speed. Never negative:
   * beating the straight-line time means the wind helped, not that you did.
   */
  private delayForArrival(ac: Aircraft, runwayIdent: string): number {
    const runway = this.airspace.runway(runwayIdent);
    if (runway === undefined) return 0;
    const straightNm = distanceNm(ac.entryPosition, runway.threshold);
    const nominalKt = Math.max(180, ac.profile.speeds.typicalCruiseIasKt);
    const nominalSec = (straightNm / nominalKt) * 3600;
    return Math.max(0, this.timeSec - ac.entryTimeSec - nominalSec);
  }

  /** The session as a supervisor would read it. */
  score(): SessionScore {
    return computeScore({
      elapsedSec: this.timeSec - this.startedAtSec,
      arrivals: this.arrivals,
      departures: this.departures,
      goArounds: this.goArounds,
      fuelBurntKg: this.fuelBurntKg,
      arrivalDelaysSec: this.arrivalDelaysSec,
      violations: this.safety.violations,
      onFrequency: this.aircraft.length,
    });
  }

  private removeLandedAircraft(): void {
    if (this.landedIds.size === 0) return;
    this.aircraft = this.aircraft.filter((ac) => !this.landedIds.has(ac.id));
    this.landedIds.clear();
  }

  /**
   * Send an aircraft around on instruction. Returns what the crew say back,
   * or null if it was not on an approach in the first place.
   */
  requestGoAround(ac: Aircraft, reason: string): string | null {
    const runway = ac.approach?.runway;
    if (runway === undefined) return null;
    const nav: NavContext = {
      airspace: this.airspace,
      wind: this.windAt(ac.altitudeFt),
      dtSec: 0,
      timeSec: this.timeSec,
      isRunwayOccupied: (ident) => this.isRunwayOccupied(ident),
    };
    const reports: string[] = [];
    goAround(ac, nav, runway, reason, reports);
    this.goArounds += 1;
    return reports.join(', ');
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
      // A departure that has been handed on and has left the airspace is a
      // movement completed.
      if (ac.role === 'departure') this.departures += 1;
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
    if (isOutOfContact(ac)) {
      // A radio failure is not a parse error: the transmission goes out, it
      // is simply not answered, and the aircraft carries on as last cleared.
      this.say('atc', ac.callsign, `${ac.callsign}, ${describe(line)}`, false);
      this.say('system', ac.callsign, `${ac.callsign} does not answer — squawking ${ac.squawk}.`, true);
      return null;
    }
    this.say('atc', ac.callsign, `${ac.callsign}, ${describe(line)}`, false);
    const outcome = executeCommands(ac, parsed.value.commands, {
      airspace: this.airspace,
      departureRunway: this.runways.departure,
      isRunwayOccupied: (ident) => this.isRunwayOccupied(ident),
      occupyRunway: (ident, seconds) => this.occupyRunway(ident, seconds),
      timeSec: this.timeSec,
      goAround: (target, reason) => this.requestGoAround(target, reason),
    });
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

/** ATIS letters run A to Z and back to A. */
export function nextAtisLetter(letter: string): string {
  const code = letter.toUpperCase().charCodeAt(0);
  if (Number.isNaN(code) || code < 65 || code > 90) return 'A';
  return code === 90 ? 'A' : String.fromCharCode(code + 1);
}

/** Echo the controller's own transmission back into the log, tidied up. */
function describe(line: string): string {
  const tokens = line.trim().split(/\s+/);
  return tokens.slice(1).join(' ').toLowerCase();
}
