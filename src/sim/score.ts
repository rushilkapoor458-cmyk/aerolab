/**
 * The session score.
 *
 * Nothing here is a points total. These are the figures a watch supervisor
 * would actually look at: what you moved, how long you made it take, what it
 * cost in fuel, and what you broke.
 */

import { Violation } from './safety.js';

export interface ScoreInput {
  /** Simulated seconds since the session began. */
  readonly elapsedSec: number;
  readonly arrivals: number;
  readonly departures: number;
  readonly goArounds: number;
  readonly fuelBurntKg: number;
  /** Per landed aircraft, seconds spent over and above a straight-in run. */
  readonly arrivalDelaysSec: readonly number[];
  readonly violations: readonly Violation[];
  readonly onFrequency: number;
}

export interface SessionScore {
  readonly elapsedSec: number;
  readonly arrivals: number;
  readonly departures: number;
  readonly movements: number;
  readonly movementsPerHour: number;
  readonly goArounds: number;
  readonly separationLosses: number;
  readonly wakeViolations: number;
  readonly terrainAlerts: number;
  readonly sectorExits: number;
  readonly totalViolations: number;
  readonly fuelBurntKg: number;
  readonly averageDelaySec: number;
  readonly worstDelaySec: number;
  readonly onFrequency: number;
}

export function computeScore(input: ScoreInput): SessionScore {
  const movements = input.arrivals + input.departures;
  const hours = input.elapsedSec / 3600;
  const delays = input.arrivalDelaysSec;
  const total = delays.reduce((sum, d) => sum + d, 0);

  const count = (kind: Violation['kind']): number =>
    input.violations.filter((v) => v.kind === kind).length;

  return {
    elapsedSec: input.elapsedSec,
    arrivals: input.arrivals,
    departures: input.departures,
    movements,
    movementsPerHour: hours > 0 ? movements / hours : 0,
    goArounds: input.goArounds,
    separationLosses: count('stca'),
    wakeViolations: count('wake'),
    terrainAlerts: count('msaw'),
    sectorExits: count('sector-exit'),
    totalViolations: input.violations.length,
    fuelBurntKg: input.fuelBurntKg,
    averageDelaySec: delays.length === 0 ? 0 : total / delays.length,
    worstDelaySec: delays.length === 0 ? 0 : Math.max(...delays),
    onFrequency: input.onFrequency,
  };
}

/** Minutes and seconds, the way a delay is usually quoted. */
export function formatDuration(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return `${minutes}:${rest < 10 ? '0' : ''}${rest}`;
}
