/** Clock, ATIS, runways in use, wind and the simulation rate control. */

import { formatBearing } from '../sim/geo.js';
import { formatClock, pad2 } from '../sim/units.js';
import { formatMetar } from '../sim/weather.js';
import { Simulation } from '../sim/world.js';

export class StatusBar {
  private readonly clock: HTMLElement;
  private readonly atis: HTMLElement;
  private readonly arr: HTMLElement;
  private readonly dep: HTMLElement;
  private readonly wind: HTMLElement;
  private readonly qnh: HTMLElement;
  private readonly atisText: HTMLElement;
  private readonly rateButtons: HTMLButtonElement[];

  constructor(
    private readonly sim: Simulation,
    private readonly onRateChange: (rate: number) => void,
  ) {
    this.clock = requireElement('status-clock');
    this.atis = requireElement('status-atis');
    this.arr = requireElement('status-arr');
    this.dep = requireElement('status-dep');
    this.wind = requireElement('status-wind');
    this.qnh = requireElement('status-qnh');
    this.atisText = requireElement('atis-text');

    const group = requireElement('rate-buttons');
    this.rateButtons = Array.from(group.querySelectorAll<HTMLButtonElement>('button.rate'));
    for (const button of this.rateButtons) {
      button.addEventListener('click', () => {
        this.onRateChange(Number(button.dataset['rate'] ?? '1'));
      });
    }
  }

  update(rate: number): void {
    const w = this.sim.weather;
    this.clock.textContent = formatClock(this.sim.timeSec);
    this.atis.textContent = w.atisLetter;
    this.arr.textContent = this.sim.runways.arrival;
    this.dep.textContent = this.sim.runways.departure;
    const gust = w.windGustKt === null ? '' : `G${pad2(Math.round(w.windGustKt))}`;
    this.wind.textContent = `${formatBearing(w.windDirectionDeg)}/${pad2(Math.round(w.windSpeedKt))}${gust}`;
    this.qnh.textContent = String(Math.round(w.qnhHpa));

    const metar = formatMetar(this.sim.airspace.airport.icao, this.sim.timeSec, w);
    const runway = this.sim.airspace.runway(this.sim.runways.arrival);
    this.atisText.textContent =
      `${this.sim.airspace.airport.icao} information ${w.atisLetter}\n` +
      `${metar}\n` +
      `Runway in use ${this.sim.runways.arrival}` +
      (runway === undefined ? '' : ` (${runway.category}, ILS ${runway.ilsFrequencyMhz.toFixed(2)})`) +
      `\nWind aloft ${formatBearing(w.windAloftDirectionDeg)}/${pad2(Math.round(w.windAloftSpeedKt))} at ${Math.round(w.windAloftAltitudeFt).toLocaleString('en-GB')} ft` +
      `\nTransition altitude ${this.sim.airspace.airport.transitionAltitudeFt} ft`;

    for (const button of this.rateButtons) {
      button.classList.toggle('active', Number(button.dataset['rate'] ?? '1') === rate);
    }
  }
}

export function requireElement(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (element === null) throw new Error(`index.html is missing the element #${id}`);
  return element;
}

export function requireInput(id: string): HTMLInputElement {
  const element = requireElement(id);
  if (!(element instanceof HTMLInputElement)) throw new Error(`#${id} is not an input`);
  return element;
}

export function requireSelect(id: string): HTMLSelectElement {
  const element = requireElement(id);
  if (!(element instanceof HTMLSelectElement)) throw new Error(`#${id} is not a select`);
  return element;
}
