/**
 * Per-type performance profiles.
 *
 * Climb and descent rates are tabulated against altitude and scaled by the
 * aircraft's current mass, so a heavy 777 leaving Delhi climbs nothing like
 * an empty Q400, and neither of them climbs at the same rate at 14,000 ft as
 * they did off the runway.
 */

import { FlightPhase, WakeCategory } from './types.js';
import { clamp } from './units.js';

export interface RatePoint {
  readonly altitudeFt: number;
  readonly rateFpm: number;
}

export interface MassEnvelope {
  readonly referenceKg: number;
  readonly minimumKg: number;
  readonly maximumKg: number;
}

export interface SpeedEnvelope {
  /** Slowest the aircraft will fly without configuring for landing. */
  readonly minCleanIasKt: number;
  /** Final approach speed, used once it is established on the approach. */
  readonly approachIasKt: number;
  readonly maxIasKt: number;
  readonly typicalCruiseIasKt: number;
}

export interface AxisLimits {
  readonly levelKtPerSec: number;
  readonly climbKtPerSec: number;
  readonly descentKtPerSec: number;
}

export interface FuelBurn {
  readonly climb: number;
  readonly cruise: number;
  readonly descent: number;
  readonly approach: number;
}

export interface AircraftProfile {
  readonly icao: string;
  readonly name: string;
  readonly wake: WakeCategory;
  readonly engine: 'jet' | 'turboprop' | 'piston';
  readonly mass: MassEnvelope;
  readonly speeds: SpeedEnvelope;
  readonly ceilingFt: number;
  readonly climbRateFpm: readonly RatePoint[];
  readonly descentRateFpm: readonly RatePoint[];
  readonly acceleration: AxisLimits;
  readonly deceleration: AxisLimits;
  /** Multiplier applied to the tabulated rate when told to expedite. */
  readonly expediteFactor: number;
  readonly fuelBurnKgPerHour: FuelBurn;
  readonly fuelCapacityKg: number;
  readonly typicalArrivalFuelKg: number;
}

export interface RawPerformance {
  schemaVersion: number;
  types: AircraftProfile[];
}

/** Nothing is ever allowed to sink into a rate too small to be flyable. */
const MINIMUM_RATE_FPM = 150;
/** Mass scaling is a first order effect; do not let it run away. */
const MASS_FACTOR_LIMITS = { min: 0.45, max: 1.6 } as const;

export class PerformanceCatalogue {
  private readonly byIcao: ReadonlyMap<string, AircraftProfile>;

  constructor(raw: RawPerformance) {
    const profiles = raw.types.map((profile) => {
      assertSorted(profile.icao, 'climb', profile.climbRateFpm);
      assertSorted(profile.icao, 'descent', profile.descentRateFpm);
      return profile;
    });
    this.byIcao = new Map(profiles.map((p) => [p.icao.toUpperCase(), p]));
  }

  get(icao: string): AircraftProfile | undefined {
    return this.byIcao.get(icao.toUpperCase());
  }

  /** Look up a type, failing loudly: a scenario naming an unknown type is a bug. */
  require(icao: string): AircraftProfile {
    const profile = this.get(icao);
    if (profile === undefined) {
      throw new Error(
        `aircraft.json has no performance profile for ${icao}. Known types: ${this.icaoCodes().join(', ')}`,
      );
    }
    return profile;
  }

  icaoCodes(): string[] {
    return [...this.byIcao.keys()].sort();
  }

  all(): readonly AircraftProfile[] {
    return [...this.byIcao.values()];
  }
}

function assertSorted(icao: string, which: string, table: readonly RatePoint[]): void {
  if (table.length === 0) throw new Error(`${icao} has an empty ${which} rate table`);
  for (let i = 1; i < table.length; i++) {
    const previous = table[i - 1];
    const current = table[i];
    if (previous === undefined || current === undefined) continue;
    if (current.altitudeFt <= previous.altitudeFt) {
      throw new Error(`${icao} ${which} rate table is not in ascending altitude order`);
    }
  }
}

/**
 * Linear interpolation through a rate table, held flat beyond either end.
 */
export function interpolateRate(table: readonly RatePoint[], altitudeFt: number): number {
  const first = table[0];
  const last = table[table.length - 1];
  if (first === undefined || last === undefined) return 0;
  if (altitudeFt <= first.altitudeFt) return first.rateFpm;
  if (altitudeFt >= last.altitudeFt) return last.rateFpm;

  for (let i = 1; i < table.length; i++) {
    const lower = table[i - 1];
    const upper = table[i];
    if (lower === undefined || upper === undefined) continue;
    if (altitudeFt <= upper.altitudeFt) {
      const span = upper.altitudeFt - lower.altitudeFt;
      const t = span === 0 ? 0 : (altitudeFt - lower.altitudeFt) / span;
      return lower.rateFpm + (upper.rateFpm - lower.rateFpm) * t;
    }
  }
  return last.rateFpm;
}

/** How much a mass away from the reference helps or hurts. */
export function massFactor(profile: AircraftProfile, massKg: number): number {
  if (massKg <= 0) return 1;
  return clamp(
    profile.mass.referenceKg / massKg,
    MASS_FACTOR_LIMITS.min,
    MASS_FACTOR_LIMITS.max,
  );
}

/** Best rate of climb available now, feet per minute. */
export function climbRateFpm(
  profile: AircraftProfile,
  altitudeFt: number,
  massKg: number,
  expedite: boolean,
): number {
  const base = interpolateRate(profile.climbRateFpm, altitudeFt) * massFactor(profile, massKg);
  return Math.max(MINIMUM_RATE_FPM, base * (expedite ? profile.expediteFactor : 1));
}

/**
 * Rate of descent available now, feet per minute.
 *
 * Mass works the other way round in the descent — a heavy aircraft comes down
 * more readily than a light one — and an aircraft being asked to slow down at
 * the same time cannot use the full rate, which is the whole of the "unable to
 * go down and slow down" problem.
 */
export function descentRateFpm(
  profile: AircraftProfile,
  altitudeFt: number,
  massKg: number,
  expedite: boolean,
  decelerationDemandKt: number,
): number {
  const base = interpolateRate(profile.descentRateFpm, altitudeFt);
  const mass = 1 / massFactor(profile, massKg);
  const slowing = decelerationDemandKt > 10 ? 0.6 : decelerationDemandKt > 0 ? 0.85 : 1;
  const rate = base * clamp(mass, MASS_FACTOR_LIMITS.min, MASS_FACTOR_LIMITS.max) * slowing;
  return Math.max(MINIMUM_RATE_FPM, rate * (expedite ? profile.expediteFactor : 1));
}

/**
 * Longitudinal acceleration available, knots per second, always positive.
 * A steep turn eats into whatever thrust is spare.
 */
export function accelerationKtPerSec(
  profile: AircraftProfile,
  phase: FlightPhase,
  accelerating: boolean,
  bankDeg: number,
): number {
  const limits = accelerating ? profile.acceleration : profile.deceleration;
  const base =
    phase === 'climb'
      ? limits.climbKtPerSec
      : phase === 'descent'
        ? limits.descentKtPerSec
        : limits.levelKtPerSec;

  if (!accelerating) return base;
  const turnPenalty = Math.abs(bankDeg) > 10 ? 0.4 * (Math.abs(bankDeg) / 25) : 0;
  return Math.max(0.1, base - turnPenalty);
}

/** Fuel burn in kilograms per second for the phase of flight given. */
export function fuelBurnKgPerSec(profile: AircraftProfile, phase: FlightPhase): number {
  const perHour =
    phase === 'climb'
      ? profile.fuelBurnKgPerHour.climb
      : phase === 'descent'
        ? profile.fuelBurnKgPerHour.descent
        : phase === 'approach'
          ? profile.fuelBurnKgPerHour.approach
          : profile.fuelBurnKgPerHour.cruise;
  return perHour / 3600;
}
