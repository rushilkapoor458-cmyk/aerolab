/**
 * Autoflight: turns a clearance into a heading to fly.
 *
 * Two lateral modes exist in milestone 1. On `heading` the aircraft points at
 * the assigned magnetic heading and lets the wind drift it, which is why the
 * controller has to allow for drift on vectors. On `direct` the aircraft
 * tracks the fix, computing its own crab angle, exactly as an FMS does.
 */

import { Airspace } from './airspace.js';
import { bearingDeg, distanceNm, normalizeDeg } from './geo.js';
import { Wind, headingForTrack } from './flight.js';
import { Aircraft } from './types.js';
import { iasToTas } from './units.js';

export interface AutoflightResult {
  /** Magnetic heading to steer, or null to hold the present heading. */
  readonly targetHeadingDeg: number | null;
  /** Things the pilot would report, e.g. sequencing onto the next fix. */
  readonly reports: readonly string[];
}

/** Distance at which a fix counts as overflown, in nautical miles. */
export function fixCaptureRadiusNm(groundspeedKt: number): number {
  // Roughly ten seconds of flying, never less than half a mile.
  return Math.max(0.5, (groundspeedKt / 3600) * 10);
}

export function updateAutoflight(ac: Aircraft, airspace: Airspace, wind: Wind): AutoflightResult {
  const reports: string[] = [];

  if (ac.clearance.lateralMode === 'heading' || ac.clearance.directFix === null) {
    return { targetHeadingDeg: ac.clearance.headingDeg, reports };
  }

  const fix = airspace.fix(ac.clearance.directFix);
  if (fix === undefined) {
    // Cannot happen through the command path, which validates the fix first,
    // but a hand-edited scenario could name a fix that is not published.
    ac.clearance.lateralMode = 'heading';
    ac.clearance.headingDeg = ac.headingDeg;
    ac.clearance.directFix = null;
    reports.push(`unable to find ${ac.clearance.directFix ?? 'that fix'} in the database, maintaining present heading`);
    return { targetHeadingDeg: ac.clearance.headingDeg, reports };
  }

  const range = distanceNm(ac.position, fix.position);
  if (range <= fixCaptureRadiusNm(ac.groundspeedKt)) {
    const next = ac.route.shift();
    if (next !== undefined && airspace.fix(next) !== undefined) {
      ac.clearance.directFix = next;
      reports.push(`${fix.name} passed, proceeding ${next}`);
    } else {
      ac.clearance.lateralMode = 'heading';
      ac.clearance.headingDeg = ac.headingDeg;
      ac.clearance.directFix = null;
      reports.push(`${fix.name} passed, maintaining present heading`);
      return { targetHeadingDeg: ac.clearance.headingDeg, reports };
    }
  }

  const target = airspace.fix(ac.clearance.directFix);
  if (target === undefined) return { targetHeadingDeg: ac.clearance.headingDeg, reports };

  const desiredTrackTrue = bearingDeg(ac.position, target.position);
  const tas = iasToTas(ac.iasKt, ac.altitudeFt);
  const headingTrue = headingForTrack(desiredTrackTrue, tas, wind) ?? desiredTrackTrue;
  const headingMagnetic = normalizeDeg(headingTrue - airspace.airport.magneticVariationDeg);
  // Keep the clearance readable in the data block while tracking a fix.
  ac.clearance.headingDeg = headingMagnetic;
  ac.clearance.turnRemainingDeg = null;
  return { targetHeadingDeg: headingMagnetic, reports };
}
