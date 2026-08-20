/**
 * Live weather editing.
 *
 * Everything here writes straight into the simulation's weather, so the wind
 * change is felt by the aircraft on the very next step.
 */

import { Simulation } from '../sim/world.js';
import { Weather } from '../sim/weather.js';
import { requireElement, requireInput, requireSelect } from './statusBar.js';

type CloudCover = Weather['cloudCover'];

const COVERS: readonly CloudCover[] = ['SKC', 'FEW', 'SCT', 'BKN', 'OVC'];

export class DebugPanel {
  private readonly root: HTMLElement;
  private readonly dir: HTMLInputElement;
  private readonly speed: HTMLInputElement;
  private readonly gust: HTMLInputElement;
  private readonly vis: HTMLInputElement;
  private readonly cloud: HTMLInputElement;
  private readonly cover: HTMLSelectElement;
  private readonly qnh: HTMLInputElement;
  private readonly temp: HTMLInputElement;
  private readonly dew: HTMLInputElement;
  private readonly atis: HTMLInputElement;
  private readonly suggestion: HTMLElement;

  constructor(private readonly sim: Simulation) {
    this.root = requireElement('debug-panel');
    this.dir = requireInput('wx-dir');
    this.speed = requireInput('wx-speed');
    this.gust = requireInput('wx-gust');
    this.vis = requireInput('wx-vis');
    this.cloud = requireInput('wx-cloud');
    this.cover = requireSelect('wx-cover');
    this.qnh = requireInput('wx-qnh');
    this.temp = requireInput('wx-temp');
    this.dew = requireInput('wx-dew');
    this.atis = requireInput('wx-atis');
    this.suggestion = requireElement('wx-suggestion');

    this.load();
    for (const field of [this.dir, this.speed, this.gust, this.vis, this.cloud, this.qnh, this.temp, this.dew, this.atis]) {
      field.addEventListener('input', () => this.apply());
    }
    this.cover.addEventListener('change', () => this.apply());

    requireElement('wx-apply-runway').addEventListener('click', () => {
      this.sim.runways = this.sim.suggestedRunways();
      this.refreshSuggestion();
    });

    const toggle = requireElement('debug-toggle');
    toggle.addEventListener('click', () => {
      this.root.hidden = !this.root.hidden;
      toggle.classList.toggle('active', !this.root.hidden);
      if (!this.root.hidden) this.load();
    });
  }

  /** Fill the fields from the simulation. */
  private load(): void {
    const w = this.sim.weather;
    this.dir.value = String(Math.round(w.windDirectionDeg));
    this.speed.value = String(Math.round(w.windSpeedKt));
    this.gust.value = w.windGustKt === null ? '' : String(Math.round(w.windGustKt));
    this.vis.value = String(Math.round(w.visibilityM));
    this.cloud.value = String(Math.round(w.cloudBaseFt));
    this.cover.value = w.cloudCover;
    this.qnh.value = String(Math.round(w.qnhHpa));
    this.temp.value = String(Math.round(w.temperatureC));
    this.dew.value = String(Math.round(w.dewpointC));
    this.atis.value = w.atisLetter;
    this.refreshSuggestion();
  }

  /** Push the fields into the simulation, ignoring half-typed values. */
  private apply(): void {
    const w = this.sim.weather;
    w.windDirectionDeg = numberOr(this.dir.value, w.windDirectionDeg, 0, 360);
    w.windSpeedKt = numberOr(this.speed.value, w.windSpeedKt, 0, 99);
    w.windGustKt = this.gust.value.trim() === '' ? null : numberOr(this.gust.value, 0, 0, 99);
    w.visibilityM = numberOr(this.vis.value, w.visibilityM, 50, 9999);
    w.cloudBaseFt = numberOr(this.cloud.value, w.cloudBaseFt, 100, 20000);
    const cover = COVERS.find((c) => c === this.cover.value);
    if (cover !== undefined) w.cloudCover = cover;
    w.qnhHpa = numberOr(this.qnh.value, w.qnhHpa, 900, 1080);
    w.temperatureC = numberOr(this.temp.value, w.temperatureC, -40, 60);
    w.dewpointC = numberOr(this.dew.value, w.dewpointC, -50, 45);
    const letter = this.atis.value.trim().toUpperCase();
    if (/^[A-Z]$/.test(letter)) w.atisLetter = letter;
    this.refreshSuggestion();
  }

  private refreshSuggestion(): void {
    const suggested = this.sim.suggestedRunways();
    this.suggestion.textContent =
      suggested.arrival === this.sim.runways.arrival
        ? `Runway ${this.sim.runways.arrival} still has the best headwind.`
        : `This wind favours runway ${suggested.arrival}; ${this.sim.runways.arrival} is in use.`;
  }
}

function numberOr(text: string, fallback: number, min: number, max: number): number {
  const value = Number(text);
  if (text.trim() === '' || Number.isNaN(value)) return fallback;
  return Math.min(max, Math.max(min, value));
}
