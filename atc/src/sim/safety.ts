/**
 * The safety net: short term conflict alert, wake turbulence on final,
 * minimum safe altitude warning, and unhandled sector exits.
 *
 * It reads the traffic picture and produces two things — the alerts a
 * controller sees now, and a permanent log of every minimum that was actually
 * broken, with the worst values recorded at the closest point.
 */

import { Airspace } from './airspace.js';
import { alongTrackNm, distanceNm, pointInPolygon } from './geo.js';
import {
  ConflictAssessment,
  SeparationStandard,
  assessConflict,
  currentSeparation,
  projectedPosition,
  standardFor,
} from './separation.js';
import { Aircraft } from './types.js';
import { formatClock } from './units.js';
import { WakeMatrix } from './wake.js';

export type AlertKind = 'stca' | 'wake' | 'msaw' | 'sector-exit';
/** `caution` is a prediction, `warning` is a minimum actually broken. */
export type AlertSeverity = 'caution' | 'warning';

export interface Alert {
  /** Stable across updates, so the display does not flicker. */
  readonly id: string;
  readonly kind: AlertKind;
  readonly severity: AlertSeverity;
  readonly aircraftIds: readonly string[];
  readonly callsigns: readonly string[];
  readonly message: string;
  /** When this alert first appeared, seconds since midnight. */
  readonly sinceSec: number;
}

export interface Violation {
  readonly id: string;
  readonly kind: AlertKind;
  readonly startedAtSec: number;
  endedAtSec: number | null;
  readonly callsigns: readonly string[];
  /** The minima that applied, where the alert has them. */
  readonly requiredLateralNm: number | null;
  readonly requiredVerticalFt: number | null;
  /** The worst values actually observed while the minimum was broken. */
  actualLateralNm: number | null;
  actualVerticalFt: number | null;
  worstAtSec: number;
  detail: string;
}

/** Distance from the threshold within which wake separation is applied. */
export const WAKE_APPLIES_WITHIN_NM = 15;
/** How far ahead an unhandled aircraft is warned about leaving the sector. */
export const SECTOR_EXIT_LOOKAHEAD_SEC = 60;
/** How far ahead the terrain warning looks. */
export const MSAW_LOOKAHEAD_SEC = 30;

export class SafetyNet {
  private active = new Map<string, Alert>();
  private readonly log: Violation[] = [];
  private readonly openViolations = new Map<string, Violation>();

  constructor(
    private readonly airspace: Airspace,
    private readonly wake: WakeMatrix,
  ) {}

  get alerts(): readonly Alert[] {
    // Warnings first, then by age, so the worst thing is always at the top.
    return [...this.active.values()].sort((a, b) => {
      if (a.severity !== b.severity) return a.severity === 'warning' ? -1 : 1;
      return a.sinceSec - b.sinceSec;
    });
  }

  get violations(): readonly Violation[] {
    return this.log;
  }

  /** Alerts naming a given aircraft, worst first. */
  alertsFor(aircraftId: string): readonly Alert[] {
    return this.alerts.filter((a) => a.aircraftIds.includes(aircraftId));
  }

  /** The worst severity affecting an aircraft, or null. */
  severityFor(aircraftId: string): AlertSeverity | null {
    const alerts = this.alertsFor(aircraftId);
    if (alerts.some((a) => a.severity === 'warning')) return 'warning';
    return alerts.length > 0 ? 'caution' : null;
  }

  /** Recompute the whole picture. Called once per simulated second. */
  update(aircraft: readonly Aircraft[], timeSec: number): void {
    const next = new Map<string, Alert>();

    this.assessConflicts(aircraft, timeSec, next);
    this.assessWake(aircraft, timeSec, next);
    this.assessTerrain(aircraft, timeSec, next);
    this.assessSectorExits(aircraft, timeSec, next);

    // Close any violation whose alert has gone away.
    for (const [id, violation] of this.openViolations) {
      const alert = next.get(id);
      if (alert === undefined || alert.severity !== 'warning') {
        violation.endedAtSec = timeSec;
        this.openViolations.delete(id);
      }
    }
    this.active = next;
  }

  /* ------------------------------------------------------------- conflicts */

  private assessConflicts(
    aircraft: readonly Aircraft[],
    timeSec: number,
    next: Map<string, Alert>,
  ): void {
    for (let i = 0; i < aircraft.length; i++) {
      for (let j = i + 1; j < aircraft.length; j++) {
        const a = aircraft[i];
        const b = aircraft[j];
        if (a === undefined || b === undefined) continue;
        // An aircraft already passed to another sector is not ours to separate.
        if (a.handedOff || b.handedOff) continue;

        const standard = standardFor(a, b);
        const assessment = assessConflict(a, b, standard);
        if (assessment.severity === 'none') continue;

        const id = `stca:${[a.id, b.id].sort().join('|')}`;
        const alert = this.conflictAlert(id, a, b, standard, assessment, timeSec, next);
        next.set(id, alert);

        if (alert.severity === 'warning') {
          const now = currentSeparation(a, b);
          this.recordViolation(id, alert, timeSec, {
            requiredLateralNm: standard.lateralNm,
            requiredVerticalFt: standard.verticalFt,
            actualLateralNm: now.lateralNm,
            actualVerticalFt: now.verticalFt,
            detail: `${now.lateralNm.toFixed(2)} NM and ${Math.round(now.verticalFt)} ft at ${formatClock(timeSec)}`,
          });
        }
      }
    }
  }

  private conflictAlert(
    id: string,
    a: Aircraft,
    b: Aircraft,
    standard: SeparationStandard,
    assessment: ConflictAssessment,
    timeSec: number,
    next: Map<string, Alert>,
  ): Alert {
    const severity: AlertSeverity = assessment.severity === 'loss' ? 'warning' : 'caution';
    const message =
      assessment.severity === 'loss'
        ? `${a.callsign} / ${b.callsign} — separation lost, ` +
          `${currentSeparation(a, b).lateralNm.toFixed(1)} NM and ` +
          `${Math.round(currentSeparation(a, b).verticalFt)} ft against ${standard.lateralNm} NM / ${standard.verticalFt} ft`
        : `${a.callsign} / ${b.callsign} — predicted loss in ${assessment.timeToLossSec ?? 0} s, ` +
          `closest ${assessment.closestDistanceNm.toFixed(1)} NM`;
    return {
      id,
      kind: 'stca',
      severity,
      aircraftIds: [a.id, b.id],
      callsigns: [a.callsign, b.callsign],
      message,
      sinceSec: this.sinceFor(id, severity, timeSec, next),
    };
  }

  /* ------------------------------------------------------------------ wake */

  private assessWake(
    aircraft: readonly Aircraft[],
    timeSec: number,
    next: Map<string, Alert>,
  ): void {
    // Group aircraft cleared for the same runway, by distance to its threshold.
    const byRunway = new Map<string, { ac: Aircraft; distanceNm: number }[]>();
    for (const ac of aircraft) {
      if (ac.approach === null) continue;
      const runway = this.airspace.runway(ac.approach.runway);
      if (runway === undefined) continue;
      const distance = -alongTrackNm(ac.position, runway.threshold, runway.trueHeadingDeg);
      if (distance < 0 || distance > WAKE_APPLIES_WITHIN_NM) continue;
      const list = byRunway.get(runway.ident) ?? [];
      list.push({ ac, distanceNm: distance });
      byRunway.set(runway.ident, list);
    }

    for (const [ident, list] of byRunway) {
      list.sort((x, y) => x.distanceNm - y.distanceNm);
      for (let i = 1; i < list.length; i++) {
        const leader = list[i - 1];
        const follower = list[i];
        if (leader === undefined || follower === undefined) continue;

        const minimum = this.wake.minimumNm(leader.ac.wake, follower.ac.wake);
        const spacing = follower.distanceNm - leader.distanceNm;
        if (spacing >= minimum) continue;

        const id = `wake:${leader.ac.id}|${follower.ac.id}`;
        const alert: Alert = {
          id,
          kind: 'wake',
          severity: 'warning',
          aircraftIds: [leader.ac.id, follower.ac.id],
          callsigns: [leader.ac.callsign, follower.ac.callsign],
          message:
            `${follower.ac.callsign} (${follower.ac.wake}) is ${spacing.toFixed(1)} NM behind ` +
            `${leader.ac.callsign} (${leader.ac.wake}) on runway ${ident} — ${minimum} NM required`,
          sinceSec: this.sinceFor(id, 'warning', timeSec, next),
        };
        next.set(id, alert);
        this.recordViolation(id, alert, timeSec, {
          requiredLateralNm: minimum,
          requiredVerticalFt: null,
          actualLateralNm: spacing,
          actualVerticalFt: Math.abs(leader.ac.altitudeFt - follower.ac.altitudeFt),
          detail: `${spacing.toFixed(2)} NM in trail on runway ${ident} at ${formatClock(timeSec)}`,
        });
      }
    }
  }

  /* --------------------------------------------------------------- terrain */

  private assessTerrain(
    aircraft: readonly Aircraft[],
    timeSec: number,
    next: Map<string, Alert>,
  ): void {
    for (const ac of aircraft) {
      // Suppressed once established on an approach: the glidepath is below
      // the sector minimum by design, and so is every approach in the world.
      if (ac.approach?.localiserCaptured === true) continue;

      // No published terrain data means no terrain warning: an invented
      // figure would either cry wolf or give false comfort.
      const msa = this.airspace.minimumSafeAltitudeFt(ac.position);
      if (msa === null) continue;
      const below = ac.altitudeFt < msa;
      const aheadMsa = this.airspace.minimumSafeAltitudeFt(
        projectedPosition(ac, MSAW_LOOKAHEAD_SEC),
      );
      const willBeBelow =
        !below &&
        ac.verticalSpeedFpm < 0 &&
        aheadMsa !== null &&
        ac.altitudeFt + (ac.verticalSpeedFpm / 60) * MSAW_LOOKAHEAD_SEC < aheadMsa;
      if (!below && !willBeBelow) continue;

      const id = `msaw:${ac.id}`;
      const severity: AlertSeverity = below ? 'warning' : 'caution';
      const alert: Alert = {
        id,
        kind: 'msaw',
        severity,
        aircraftIds: [ac.id],
        callsigns: [ac.callsign],
        message: below
          ? `${ac.callsign} — terrain, ${Math.round(ac.altitudeFt)} ft against a minimum of ${msa} ft`
          : `${ac.callsign} — descending towards the minimum safe altitude of ${msa} ft`,
        sinceSec: this.sinceFor(id, severity, timeSec, next),
      };
      next.set(id, alert);

      if (below) {
        this.recordViolation(id, alert, timeSec, {
          requiredLateralNm: null,
          requiredVerticalFt: msa,
          actualLateralNm: null,
          actualVerticalFt: ac.altitudeFt,
          detail: `${Math.round(ac.altitudeFt)} ft against a minimum of ${msa} ft at ${formatClock(timeSec)}`,
        });
      }
    }
  }

  /* ---------------------------------------------------------- sector exits */

  private assessSectorExits(
    aircraft: readonly Aircraft[],
    timeSec: number,
    next: Map<string, Alert>,
  ): void {
    const boundary = this.airspace.sector.boundary;
    for (const ac of aircraft) {
      if (ac.handedOff) continue;
      const inside = pointInPolygon(ac.position, boundary);
      const willLeave =
        inside && !pointInPolygon(projectedPosition(ac, SECTOR_EXIT_LOOKAHEAD_SEC), boundary);
      if (inside && !willLeave) continue;

      const id = `exit:${ac.id}`;
      const severity: AlertSeverity = inside ? 'caution' : 'warning';
      const alert: Alert = {
        id,
        kind: 'sector-exit',
        severity,
        aircraftIds: [ac.id],
        callsigns: [ac.callsign],
        message: inside
          ? `${ac.callsign} — leaving the sector within a minute and not handed off`
          : `${ac.callsign} — outside the sector and still on your frequency`,
        sinceSec: this.sinceFor(id, severity, timeSec, next),
      };
      next.set(id, alert);

      if (!inside) {
        this.recordViolation(id, alert, timeSec, {
          requiredLateralNm: null,
          requiredVerticalFt: null,
          actualLateralNm: distanceNm(ac.position, { x: 0, y: 0 }),
          actualVerticalFt: ac.altitudeFt,
          detail: `left the sector unhandled at ${formatClock(timeSec)}`,
        });
      }
    }
  }

  /* ----------------------------------------------------------------- state */

  /**
   * Keep the original timestamp while an alert persists, but restart it if the
   * severity changes, so an escalation reads as a new event.
   */
  private sinceFor(
    id: string,
    severity: AlertSeverity,
    timeSec: number,
    next: Map<string, Alert>,
  ): number {
    const existing = next.get(id) ?? this.active.get(id);
    if (existing !== undefined && existing.severity === severity) return existing.sinceSec;
    return timeSec;
  }

  private recordViolation(
    id: string,
    alert: Alert,
    timeSec: number,
    values: {
      requiredLateralNm: number | null;
      requiredVerticalFt: number | null;
      actualLateralNm: number | null;
      actualVerticalFt: number | null;
      detail: string;
    },
  ): void {
    const open = this.openViolations.get(id);
    if (open === undefined) {
      const violation: Violation = {
        id: `${id}@${Math.round(timeSec)}`,
        kind: alert.kind,
        startedAtSec: timeSec,
        endedAtSec: null,
        callsigns: [...alert.callsigns],
        requiredLateralNm: values.requiredLateralNm,
        requiredVerticalFt: values.requiredVerticalFt,
        actualLateralNm: values.actualLateralNm,
        actualVerticalFt: values.actualVerticalFt,
        worstAtSec: timeSec,
        detail: values.detail,
      };
      this.log.push(violation);
      this.openViolations.set(id, violation);
      return;
    }

    // Keep the worst values seen, which is what the report has to show.
    const worseLaterally =
      values.actualLateralNm !== null &&
      (open.actualLateralNm === null || values.actualLateralNm < open.actualLateralNm);
    const worseVertically =
      alert.kind === 'msaw' &&
      values.actualVerticalFt !== null &&
      (open.actualVerticalFt === null || values.actualVerticalFt < open.actualVerticalFt);
    if (worseLaterally || worseVertically) {
      open.actualLateralNm = values.actualLateralNm;
      open.actualVerticalFt = values.actualVerticalFt;
      open.worstAtSec = timeSec;
      open.detail = values.detail;
    }
  }
}
