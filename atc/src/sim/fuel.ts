/**
 * Fuel burn and what happens when it runs low.
 *
 * Burn is per phase of flight, taken from the aircraft's profile. The state
 * escalates and never comes back down: an aircraft that has declared minimum
 * fuel stays declared, because the crew's planning has already changed.
 */

import { fuelBurnKgPerSec } from './performance.js';
import { Aircraft, FuelState } from './types.js';

/** Below this endurance the crew advise minimum fuel. */
export const MINIMUM_FUEL_MINUTES = 30;
/** Below this endurance they declare an emergency and squawk 7700. */
export const EMERGENCY_FUEL_MINUTES = 15;
export const EMERGENCY_SQUAWK = '7700';

/** Endurance in minutes at the current phase's burn rate. */
export function enduranceMinutes(ac: Aircraft): number {
  const perSec = fuelBurnKgPerSec(ac.profile, ac.phase);
  if (perSec <= 0) return Infinity;
  return ac.fuelKg / perSec / 60;
}

/** State the endurance implies, ignoring any escalation already made. */
export function stateForEndurance(minutes: number): FuelState {
  if (minutes <= EMERGENCY_FUEL_MINUTES) return 'emergency';
  if (minutes <= MINIMUM_FUEL_MINUTES) return 'minimum';
  return 'normal';
}

const ORDER: Record<FuelState, number> = { normal: 0, minimum: 1, emergency: 2 };

/**
 * Burn fuel for `dtSec` and escalate the state if need be. Returns anything
 * the crew would transmit — usually nothing at all.
 */
export function updateFuel(ac: Aircraft, dtSec: number, fieldElevationFt: number): string[] {
  const transmissions: string[] = [];
  const burnKg = fuelBurnKgPerSec(ac.profile, ac.phase) * dtSec;
  const burnt = Math.min(ac.fuelKg, burnKg);
  ac.fuelKg -= burnt;
  ac.massKg -= burnt;

  const minutes = enduranceMinutes(ac);
  const wanted = stateForEndurance(minutes);
  if (ORDER[wanted] > ORDER[ac.fuelState]) {
    ac.fuelState = wanted;
    if (wanted === 'minimum') {
      transmissions.push(
        `${ac.callsign}, we are declaring minimum fuel, ${Math.round(minutes)} minutes remaining — we can accept no undue delay`,
      );
    } else {
      ac.squawk = EMERGENCY_SQUAWK;
      transmissions.push(
        `MAYDAY MAYDAY MAYDAY, ${ac.callsign}, fuel emergency, ${Math.round(minutes)} minutes remaining, squawking ${EMERGENCY_SQUAWK}, request priority to land`,
      );
    }
  }

  // Dry tanks: the aircraft cannot hold its level any more, whatever it is
  // cleared to. It descends towards the ground at its profile's rate.
  if (ac.fuelKg <= 0 && ac.clearance.altitudeFt > fieldElevationFt) {
    ac.clearance.altitudeFt = fieldElevationFt;
    ac.clearance.expedite = false;
    transmissions.push(`${ac.callsign}, we have flamed out, we are gliding — unable to maintain altitude`);
  }

  return transmissions;
}

/** Fuel remaining phrased the way a crew would answer "say fuel remaining". */
export function fuelReport(ac: Aircraft): string {
  const minutes = enduranceMinutes(ac);
  const kg = Math.round(ac.fuelKg / 10) * 10;
  const spoken = Number.isFinite(minutes) ? `${Math.round(minutes)} minutes` : 'indefinite endurance';
  return `${kg} kilos remaining, that is about ${spoken}`;
}
