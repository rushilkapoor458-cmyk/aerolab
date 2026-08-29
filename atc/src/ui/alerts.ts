/** The safety net panel: everything the system is shouting about, worst first. */

import { Alert } from '../sim/safety.js';
import { formatClock } from '../sim/units.js';

const KIND_LABEL: Record<Alert['kind'], string> = {
  stca: 'STCA',
  wake: 'WAKE',
  msaw: 'MSAW',
  'sector-exit': 'EXIT',
};

export class AlertsPanel {
  private lastSignature = '';

  constructor(
    private readonly root: HTMLElement,
    private readonly onSelect: (aircraftId: string) => void,
  ) {}

  update(alerts: readonly Alert[]): void {
    const signature = alerts.map((a) => `${a.id}:${a.severity}:${a.message}`).join(';');
    if (signature === this.lastSignature) return;
    this.lastSignature = signature;

    this.root.replaceChildren();
    if (alerts.length === 0) {
      const clear = document.createElement('div');
      clear.className = 'alert-clear';
      clear.textContent = 'No alerts.';
      this.root.append(clear);
      return;
    }

    for (const alert of alerts) {
      const row = document.createElement('div');
      row.className = `alert-row ${alert.severity}`;

      const kind = document.createElement('span');
      kind.className = 'alert-kind';
      kind.textContent = KIND_LABEL[alert.kind];

      const text = document.createElement('span');
      text.className = 'alert-text';
      text.textContent = alert.message;

      const since = document.createElement('span');
      since.className = 'alert-since';
      since.textContent = formatClock(alert.sinceSec).slice(0, 5);

      row.append(kind, text, since);
      const first = alert.aircraftIds[0];
      if (first !== undefined) row.addEventListener('click', () => this.onSelect(first));
      this.root.append(row);
    }
  }
}
