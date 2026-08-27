/**
 * The session report: the score, and every minimum that was actually broken.
 */

import { Violation } from '../sim/safety.js';
import { SessionScore, formatDuration } from '../sim/score.js';
import { formatClock } from '../sim/units.js';
import { Simulation } from '../sim/world.js';

const KIND_LABEL: Record<Violation['kind'], string> = {
  stca: 'Separation',
  wake: 'Wake turbulence',
  msaw: 'Terrain',
  'sector-exit': 'Sector exit',
};

export class ScoreOverlay {
  private open = false;

  constructor(
    private readonly root: HTMLElement,
    private readonly sim: Simulation,
  ) {
    this.root.hidden = true;
    this.root.addEventListener('click', () => this.hide());
  }

  toggle(): void {
    if (this.open) this.hide();
    else this.show();
  }

  show(): void {
    this.root.innerHTML = render(this.sim.score(), this.sim.safety.violations);
    this.open = true;
    this.root.hidden = false;
  }

  hide(): void {
    this.open = false;
    this.root.hidden = true;
  }

  get isOpen(): boolean {
    return this.open;
  }
}

function render(score: SessionScore, violations: readonly Violation[]): string {
  return [
    '<h1>Session report</h1>',
    `<p>${formatDuration(score.elapsedSec)} on position · ${score.onFrequency} aircraft on frequency.</p>`,
    '<h2>Movements</h2>',
    stats([
      ['Arrivals landed', String(score.arrivals)],
      ['Departures away', String(score.departures)],
      ['Movements per hour', score.movementsPerHour.toFixed(1)],
      ['Go-arounds', String(score.goArounds)],
    ]),
    '<h2>Efficiency</h2>',
    stats([
      ['Average delay', formatDuration(score.averageDelaySec)],
      ['Worst delay', formatDuration(score.worstDelaySec)],
      ['Fuel burnt', `${Math.round(score.fuelBurntKg).toLocaleString('en-GB')} kg`],
    ]),
    '<h2>Safety</h2>',
    stats([
      ['Separation losses', String(score.separationLosses)],
      ['Wake turbulence', String(score.wakeViolations)],
      ['Terrain alerts', String(score.terrainAlerts)],
      ['Unhandled sector exits', String(score.sectorExits)],
    ]),
    '<h2>Violation log</h2>',
    violationTable(violations),
    '<p class="close">Click anywhere, or press Escape, to close.</p>',
  ].join('');
}

function stats(rows: readonly (readonly [string, string])[]): string {
  const cells = rows
    .map(
      ([label, value]) =>
        `<div class="stat"><span class="stat-label">${escapeHtml(label)}</span>` +
        `<span class="stat-value">${escapeHtml(value)}</span></div>`,
    )
    .join('');
  return `<div class="stat-row">${cells}</div>`;
}

function violationTable(violations: readonly Violation[]): string {
  if (violations.length === 0) {
    return '<p>Nothing broken. Every minimum held for the whole session.</p>';
  }
  const rows = violations
    .map((v) => {
      const required =
        v.requiredLateralNm !== null && v.requiredVerticalFt !== null
          ? `${v.requiredLateralNm} NM / ${v.requiredVerticalFt} ft`
          : v.requiredLateralNm !== null
            ? `${v.requiredLateralNm} NM`
            : v.requiredVerticalFt !== null
              ? `${v.requiredVerticalFt} ft`
              : '—';
      const actual =
        v.kind === 'msaw'
          ? `${Math.round(v.actualVerticalFt ?? 0)} ft`
          : v.actualLateralNm === null
            ? '—'
            : `${v.actualLateralNm.toFixed(2)} NM` +
              (v.actualVerticalFt === null ? '' : ` / ${Math.round(v.actualVerticalFt)} ft`);
      const duration =
        v.endedAtSec === null ? 'ongoing' : formatDuration(v.endedAtSec - v.startedAtSec);
      return (
        '<tr>' +
        `<td>${formatClock(v.startedAtSec)}</td>` +
        `<td>${escapeHtml(KIND_LABEL[v.kind])}</td>` +
        `<td>${escapeHtml(v.callsigns.join(' / '))}</td>` +
        `<td>${escapeHtml(required)}</td>` +
        `<td class="worst">${escapeHtml(actual)}</td>` +
        `<td>${escapeHtml(formatClock(v.worstAtSec))}</td>` +
        `<td>${escapeHtml(duration)}</td>` +
        '</tr>'
      );
    })
    .join('');
  return (
    '<table class="log"><thead><tr>' +
    '<th>Time</th><th>Kind</th><th>Aircraft</th><th>Required</th>' +
    '<th>At closest point</th><th>Closest at</th><th>Duration</th>' +
    '</tr></thead><tbody>' +
    rows +
    '</tbody></table>'
  );
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
