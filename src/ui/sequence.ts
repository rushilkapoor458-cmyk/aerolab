/**
 * The arrival sequence panel: everything inbound, nearest the field first.
 *
 * This is a read-only view of the order traffic will actually arrive in.
 * The flight strip bay, with strips you drag to set your intended sequence,
 * is milestone 5.
 */

import { distanceNm } from '../sim/geo.js';
import { Aircraft } from '../sim/types.js';
import { formatFlightLevel } from '../sim/units.js';
import { Simulation } from '../sim/world.js';

export interface SequenceRow {
  readonly id: string;
  readonly callsign: string;
  readonly state: string;
  readonly rangeNm: number;
  readonly altitudeFt: number;
  readonly onApproach: boolean;
  readonly holding: boolean;
}

/** What the aircraft is doing, in the fewest words that are still exact. */
export function sequenceState(ac: Aircraft): string {
  if (ac.approach !== null) {
    if (ac.approach.glideslopeCaptured) return `ILS ${ac.approach.runway} G/S`;
    if (ac.approach.localiserCaptured) return `ILS ${ac.approach.runway} LOC`;
    return `ILS ${ac.approach.runway} vectors`;
  }
  if (ac.hold !== null) return `hold ${ac.hold.fix}`;
  if (ac.handedOff) return `to ${ac.handedOffTo ?? 'next sector'}`;
  if (ac.clearance.lateralMode === 'direct' && ac.clearance.directFix !== null) {
    return ac.procedure === null ? `dct ${ac.clearance.directFix}` : `${ac.procedure} · ${ac.clearance.directFix}`;
  }
  return `heading ${Math.round(ac.clearance.headingDeg).toString().padStart(3, '0')}`;
}

/** Arrivals, closest to the aerodrome first. */
export function buildSequence(sim: Simulation): SequenceRow[] {
  const field = { x: 0, y: 0 };
  return sim.aircraft
    .filter((ac) => ac.role === 'arrival')
    .map((ac) => ({
      id: ac.id,
      callsign: ac.callsign,
      state: sequenceState(ac),
      rangeNm: distanceNm(ac.position, field),
      altitudeFt: ac.altitudeFt,
      onApproach: ac.approach !== null,
      holding: ac.hold !== null,
    }))
    .sort((a, b) => a.rangeNm - b.rangeNm);
}

export class SequencePanel {
  private lastSignature = '';

  constructor(
    private readonly root: HTMLElement,
    private readonly sim: Simulation,
    private readonly onSelect: (id: string) => void,
  ) {}

  update(selectedId: string | null): void {
    const rows = buildSequence(this.sim);
    // Rebuilding the list every frame would fight the pointer; only redraw
    // when something the controller can see has actually changed.
    const signature = rows
      .map((r) => `${r.id}|${r.state}|${r.rangeNm.toFixed(1)}|${Math.round(r.altitudeFt / 100)}`)
      .join(';') + `#${selectedId ?? ''}`;
    if (signature === this.lastSignature) return;
    this.lastSignature = signature;

    this.root.replaceChildren();
    if (rows.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'seq-empty';
      empty.textContent = 'No arrivals on frequency.';
      this.root.append(empty);
      return;
    }

    rows.forEach((row, index) => {
      const element = document.createElement('div');
      element.className = 'seq-row';
      if (row.onApproach) element.classList.add('on-approach');
      if (row.holding) element.classList.add('holding');
      if (row.id === selectedId) element.classList.add('selected');

      element.append(
        cell('seq-index', String(index + 1)),
        cell('seq-callsign', row.callsign),
        cell('seq-state', row.state),
        cell('seq-range', `${row.rangeNm.toFixed(1)}`),
        cell('seq-alt', formatFlightLevel(row.altitudeFt)),
      );
      element.addEventListener('click', () => this.onSelect(row.id));
      this.root.append(element);
    });
  }
}

function cell(className: string, text: string): HTMLElement {
  const span = document.createElement('span');
  span.className = className;
  span.textContent = text;
  return span;
}
