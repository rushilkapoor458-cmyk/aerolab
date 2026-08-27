/**
 * The scenario picker.
 *
 * Choosing one reloads the page against it, so every session starts from a
 * clean simulation seeded by that scenario — no half-torn-down state.
 */

import { SCENARIOS } from '../sim/scenarios.js';
import { Scenario } from '../sim/scenario.js';

export class ScenarioPicker {
  private open = false;

  constructor(
    private readonly root: HTMLElement,
    private readonly current: Scenario | null,
  ) {
    this.root.hidden = true;
    this.render();
  }

  toggle(): void {
    if (this.open) this.hide();
    else this.show();
  }

  show(): void {
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

  private render(): void {
    this.root.replaceChildren();

    const heading = document.createElement('h1');
    heading.textContent = 'Scenarios';
    const note = document.createElement('p');
    note.textContent =
      'Each one runs from its own seed, so the same scenario always plays out the same way. Choosing one starts a fresh session.';
    this.root.append(heading, note);

    const list = document.createElement('div');
    list.className = 'scenario-list';

    for (const scenario of SCENARIOS) {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'scenario-card';
      if (scenario.id === this.current?.id) card.classList.add('current');

      const name = document.createElement('span');
      name.className = 'scenario-name';
      name.textContent = scenario.name;

      const rate = document.createElement('span');
      rate.className = 'scenario-rate';
      const movements = scenario.traffic.arrivalsPerHour + scenario.traffic.departuresPerHour;
      rate.textContent =
        movements === 0
          ? `${scenario.durationMin} min · scripted traffic`
          : `${scenario.durationMin} min · ${movements} movements an hour`;

      const description = document.createElement('span');
      description.className = 'scenario-description';
      description.textContent = scenario.description;

      card.append(name, rate, description);
      card.addEventListener('click', (event) => {
        event.stopPropagation();
        window.location.search = `?scenario=${encodeURIComponent(scenario.id)}`;
      });
      list.append(card);
    }

    const close = document.createElement('p');
    close.className = 'close';
    close.textContent = 'Press Escape to close without changing scenario.';

    this.root.append(list, close);
  }
}
