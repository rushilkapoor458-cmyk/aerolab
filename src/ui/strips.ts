/**
 * The flight strip bay.
 *
 * Arrivals and departures are kept apart, as they are on a real bay. The
 * arrival strips can be dragged into the order you intend to land them in;
 * that order is yours, not the simulation's, so a strip out of position
 * against the actual order is marked rather than corrected.
 */

import { distanceNm } from '../sim/geo.js';
import { Aircraft } from '../sim/types.js';
import { formatFlightLevel } from '../sim/units.js';
import { Simulation } from '../sim/world.js';

export interface StripRow {
  readonly id: string;
  readonly callsign: string;
  readonly type: string;
  readonly wake: string;
  readonly state: string;
  readonly rangeNm: number;
  readonly altitudeFt: number;
  readonly speedKt: number;
  readonly alert: 'none' | 'caution' | 'alert';
  readonly onApproach: boolean;
  readonly holding: boolean;
}

/** What the aircraft is doing, in the fewest words that are still exact. */
export function stripState(ac: Aircraft): string {
  if (ac.ground === 'queue') return 'holding point';
  if (ac.ground === 'lineup') return `lined up ${ac.departureRunway ?? ''}`.trim();
  if (ac.ground === 'takeoff') return 'rolling';
  if (ac.emergency === 'radio') return 'no radio — last clearance';
  if (ac.approach !== null) {
    if (ac.approach.glideslopeCaptured) return `ILS ${ac.approach.runway} G/S`;
    if (ac.approach.localiserCaptured) return `ILS ${ac.approach.runway} LOC`;
    return `ILS ${ac.approach.runway} vectors`;
  }
  if (ac.hold !== null) return `hold ${ac.hold.fix}`;
  if (ac.handedOff) return `to ${ac.handedOffTo ?? 'next sector'}`;
  if (ac.clearance.lateralMode === 'direct' && ac.clearance.directFix !== null) {
    return ac.procedure === null
      ? `dct ${ac.clearance.directFix}`
      : `${ac.procedure} · ${ac.clearance.directFix}`;
  }
  return `heading ${Math.round(ac.clearance.headingDeg).toString().padStart(3, '0')}`;
}

function toRow(sim: Simulation, ac: Aircraft): StripRow {
  const severity = sim.safety.severityFor(ac.id);
  return {
    id: ac.id,
    callsign: ac.callsign,
    type: ac.type,
    wake: ac.wake,
    state: stripState(ac),
    rangeNm: distanceNm(ac.position, { x: 0, y: 0 }),
    altitudeFt: ac.altitudeFt,
    speedKt: ac.iasKt,
    alert:
      severity === 'warning' || ac.emergency !== 'none' || ac.fuelState === 'emergency'
        ? 'alert'
        : severity === 'caution' || ac.fuelState === 'minimum'
          ? 'caution'
          : 'none',
    onApproach: ac.approach !== null,
    holding: ac.hold !== null,
  };
}

/**
 * Arrivals in the controller's intended order: anything dragged keeps the
 * position it was put in, and anything new joins in range order behind.
 */
export function orderArrivals(rows: readonly StripRow[], manual: readonly string[]): StripRow[] {
  const known = rows.filter((r) => manual.includes(r.id));
  const fresh = rows.filter((r) => !manual.includes(r.id)).sort((a, b) => a.rangeNm - b.rangeNm);
  known.sort((a, b) => manual.indexOf(a.id) - manual.indexOf(b.id));
  return [...known, ...fresh];
}

export class StripBay {
  /** Arrival ids in the order the controller has dragged them into. */
  private manualOrder: string[] = [];
  private lastSignature = '';
  private dragging: string | null = null;

  constructor(
    private readonly arrivalsRoot: HTMLElement,
    private readonly departuresRoot: HTMLElement,
    private readonly sim: Simulation,
    private readonly onSelect: (id: string) => void,
  ) {}

  update(selectedId: string | null): void {
    const arrivals = this.sim.aircraft
      .filter((ac) => ac.role === 'arrival')
      .map((ac) => toRow(this.sim, ac));
    const departures = this.sim.aircraft
      .filter((ac) => ac.role === 'departure')
      .map((ac) => toRow(this.sim, ac))
      .sort((a, b) => a.rangeNm - b.rangeNm);

    const ordered = orderArrivals(arrivals, this.manualOrder);
    // Forget aircraft that have gone, and remember the ones that are new.
    this.manualOrder = ordered.map((r) => r.id);

    const signature =
      ordered.map((r) => stripSignature(r)).join(';') +
      '#' +
      departures.map((r) => stripSignature(r)).join(';') +
      `#${selectedId ?? ''}`;
    if (signature === this.lastSignature) return;
    this.lastSignature = signature;

    this.render(this.arrivalsRoot, ordered, selectedId, true);
    this.render(this.departuresRoot, departures, selectedId, false);
  }

  private render(
    root: HTMLElement,
    rows: readonly StripRow[],
    selectedId: string | null,
    draggable: boolean,
  ): void {
    root.replaceChildren();
    if (rows.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'strip-empty';
      empty.textContent = draggable ? 'No arrivals.' : 'No departures.';
      root.append(empty);
      return;
    }

    // The actual arrival order, so a strip out of position can be marked.
    const byRange = [...rows].sort((a, b) => a.rangeNm - b.rangeNm).map((r) => r.id);

    rows.forEach((row, index) => {
      const strip = document.createElement('div');
      strip.className = `strip ${row.alert}`;
      if (row.id === selectedId) strip.classList.add('selected');
      if (row.onApproach) strip.classList.add('on-approach');
      if (row.holding) strip.classList.add('holding');
      if (draggable && byRange[index] !== row.id) strip.classList.add('out-of-order');

      strip.append(
        cell('strip-index', String(index + 1)),
        cell('strip-callsign', row.callsign),
        cell('strip-type', `${row.type}/${row.wake}`),
        cell('strip-state', row.state),
        cell('strip-alt', formatFlightLevel(row.altitudeFt)),
        cell('strip-speed', String(Math.round(row.speedKt))),
        cell('strip-range', row.rangeNm.toFixed(1)),
      );
      strip.addEventListener('click', () => this.onSelect(row.id));

      if (draggable) {
        strip.draggable = true;
        strip.addEventListener('dragstart', (event) => {
          this.dragging = row.id;
          event.dataTransfer?.setData('text/plain', row.id);
          strip.classList.add('dragging');
        });
        strip.addEventListener('dragend', () => {
          this.dragging = null;
          strip.classList.remove('dragging');
        });
        strip.addEventListener('dragover', (event) => {
          event.preventDefault();
          strip.classList.add('drop-target');
        });
        strip.addEventListener('dragleave', () => strip.classList.remove('drop-target'));
        strip.addEventListener('drop', (event) => {
          event.preventDefault();
          strip.classList.remove('drop-target');
          const moved = this.dragging ?? event.dataTransfer?.getData('text/plain') ?? null;
          if (moved !== null) this.moveBefore(moved, row.id);
        });
      }

      root.append(strip);
    });
  }

  /** Put one strip immediately before another in the intended sequence. */
  moveBefore(movedId: string, targetId: string): void {
    if (movedId === targetId) return;
    const order = this.manualOrder.filter((id) => id !== movedId);
    const at = order.indexOf(targetId);
    if (at === -1) order.push(movedId);
    else order.splice(at, 0, movedId);
    this.manualOrder = order;
    // Force a redraw on the next update, since only the order has changed.
    this.lastSignature = '';
  }

  /** The intended sequence, for tests and for anything that wants to read it. */
  get intendedOrder(): readonly string[] {
    return this.manualOrder;
  }
}

function stripSignature(row: StripRow): string {
  return `${row.id}|${row.state}|${row.alert}|${Math.round(row.altitudeFt / 100)}|${Math.round(row.speedKt)}|${row.rangeNm.toFixed(1)}`;
}

function cell(className: string, text: string): HTMLElement {
  const span = document.createElement('span');
  span.className = className;
  span.textContent = text;
  return span;
}
