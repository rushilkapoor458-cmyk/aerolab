/** Core simulation types shared across the pure-logic layer. */

import { Point } from './geo.js';
import { AircraftProfile } from './performance.js';

export type WakeCategory = 'L' | 'M' | 'H' | 'J';

export type FlightRole = 'arrival' | 'departure' | 'overflight';

export type FlightPhase = 'cruise' | 'climb' | 'descent' | 'approach';

/** Where a departure is on the ground. Null means airborne. */
export type GroundState = 'queue' | 'lineup' | 'takeoff';

/** A declared emergency other than fuel, which has its own state. */
export type EmergencyState = 'none' | 'engine' | 'radio';

/**
 * How the fuel state escalates. `minimum` is an advisory — the aircraft can
 * accept no undue delay; `emergency` is a declaration, squawking 7700, and
 * the aircraft expects priority.
 */
export type FuelState = 'normal' | 'minimum' | 'emergency';

/** How the autoflight system is currently steering laterally. */
export type LateralMode = 'heading' | 'direct' | 'hold' | 'approach';

/** Where an aircraft is in the racetrack. */
export type HoldLeg = 'toFix' | 'outbound' | 'turnInbound';

export interface HoldState {
  readonly fix: string;
  readonly inboundCourseTrueDeg: number;
  readonly turnDirection: 'left' | 'right';
  readonly legTimeSec: number;
  leg: HoldLeg;
  legTimerSec: number;
  /** Set once the crew have reported entering the pattern. */
  established: boolean;
  /** Expect-further-clearance time, seconds since midnight, or null. */
  efcTimeSec: number | null;
}

export interface ApproachState {
  readonly runway: string;
  readonly ident: string;
  localiserCaptured: boolean;
  glideslopeCaptured: boolean;
  /** Set once the crew have called that they are going through the localiser. */
  reportedBlowThrough: boolean;
  /** Set once the stability gate at 1000 ft has been passed. */
  stabilityChecked: boolean;
}

/** Which way a turn was instructed to go. */
export type TurnInstruction = 'left' | 'right' | 'shortest';

/** What the autoflight has decided the aeroplane should do this step. */
export interface SteeringCommand {
  /** Magnetic heading to steer, or null to hold the present heading. */
  readonly headingDeg: number | null;
  /** Vertical speed to fly, overriding the cleared altitude. Null to ignore. */
  readonly verticalSpeedFpm: number | null;
  /** Indicated airspeed to fly, overriding the assigned speed. Null to ignore. */
  readonly speedKt: number | null;
}

export interface Clearance {
  /** Assigned magnetic heading, when the aircraft is on vectors. */
  headingDeg: number;
  /** Turn direction to use on the way to `headingDeg`. */
  turn: TurnInstruction;
  /**
   * Degrees of heading change still to fly, signed, when the controller named
   * a side. Latched when the instruction is given so that a turn the long way
   * round cannot restart itself as it rolls out onto the heading.
   */
  turnRemainingDeg: number | null;
  /** Cleared altitude in feet AMSL. */
  altitudeFt: number;
  /** Assigned indicated airspeed in knots. */
  speedKt: number;
  /** Fix the aircraft is proceeding direct to, when `lateralMode` is 'direct'. */
  directFix: string | null;
  lateralMode: LateralMode;
  /** True once the controller has cancelled the 250 kt below 10,000 ft rule. */
  speedRestrictionCancelled: boolean;
  /** True while the aircraft has been told to expedite its climb or descent. */
  expedite: boolean;
  /** True once cleared to descend via the published arrival's restrictions. */
  descendVia: boolean;
}

export interface Aircraft {
  readonly id: string;
  readonly callsign: string;
  /** ICAO type designator, e.g. `A320`. */
  readonly type: string;
  /** Performance profile for this type, from `src/data/aircraft.json`. */
  readonly profile: AircraftProfile;
  readonly wake: WakeCategory;
  readonly role: FlightRole;

  position: Point;
  altitudeFt: number;
  /** Magnetic heading the nose points along. Not the ground track. */
  headingDeg: number;
  /** Ground track in true degrees, after the wind triangle. */
  trueTrackDeg: number;
  /** Indicated airspeed, knots. */
  iasKt: number;
  /** Groundspeed, knots. */
  groundspeedKt: number;
  /** Current bank angle, positive to the right. */
  bankDeg: number;
  /** Current vertical speed, feet per minute, positive up. */
  verticalSpeedFpm: number;

  squawk: string;
  /** All-up mass in kilograms. Falls as fuel burns, and drives performance. */
  massKg: number;
  fuelKg: number;
  fuelState: FuelState;
  clearance: Clearance;
  /** Ordered list of fix names still to fly, when following a route. */
  route: string[];
  /** Published procedure the route came from, for the data block. */
  procedure: string | null;
  phase: FlightPhase;

  /** Set while established in a published holding pattern. */
  hold: HoldState | null;
  /** Set once cleared for an instrument approach. */
  approach: ApproachState | null;
  /** Counts the go-arounds this aircraft has flown. */
  goAroundCount: number;

  /** Where a departure is on the ground; null once airborne. */
  ground: GroundState | null;
  /** Runway a departure is using. */
  departureRunway: string | null;
  emergency: EmergencyState;
  /**
   * Multiplier on climb performance. One normally; well below one after an
   * engine failure, which also caps the speed the aircraft will accept.
   */
  performanceFactor: number;

  /** When and where the aircraft came onto frequency, for the delay figure. */
  readonly entryTimeSec: number;
  readonly entryPosition: Point;

  /** Position trail, oldest first, one entry per radar sweep. */
  history: Point[];
  /** Seconds until the next radar sweep records a history dot. */
  sweepTimerSec: number;

  /** Set once the aircraft has left the controller's responsibility. */
  handedOff: boolean;
  /** Who it was sent to, and on what frequency. Null until handed off. */
  handedOffTo: string | null;
  handedOffFrequencyMhz: number | null;
}

export type CommsSource = 'atc' | 'pilot' | 'system';

export interface CommsEntry {
  readonly id: number;
  readonly timeSec: number;
  readonly source: CommsSource;
  readonly callsign: string | null;
  readonly text: string;
  /** Marks a pilot refusal or a parse failure, so the panel can colour it. */
  readonly rejected: boolean;
}
