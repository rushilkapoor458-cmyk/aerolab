/** The scrolling communications panel. */

import { CommsEntry } from '../sim/types.js';
import { formatClock } from '../sim/units.js';

export class CommsPanel {
  private lastRenderedId = 0;

  constructor(private readonly root: HTMLElement) {}

  update(entries: readonly CommsEntry[]): void {
    const fresh = entries.filter((e) => e.id > this.lastRenderedId);
    if (fresh.length === 0) return;

    // Stay pinned to the bottom unless the controller has scrolled back.
    const pinned = this.root.scrollTop + this.root.clientHeight >= this.root.scrollHeight - 24;

    for (const entry of fresh) {
      const row = document.createElement('div');
      row.className = `entry ${entry.source}${entry.rejected ? ' rejected' : ''}`;

      const time = document.createElement('span');
      time.className = 'time';
      time.textContent = formatClock(entry.timeSec).slice(0, 5);

      const marker = document.createElement('span');
      marker.className = 'marker';
      marker.textContent = entry.source === 'pilot' ? '\u00ab' : entry.source === 'atc' ? '\u00bb' : '\u00b7';

      const text = document.createElement('span');
      text.className = 'text';
      text.textContent = entry.text;

      row.append(time, marker, text);
      this.root.append(row);
      this.lastRenderedId = entry.id;
    }

    // Keep the DOM bounded on a long session.
    while (this.root.childElementCount > 300) this.root.firstElementChild?.remove();
    if (pinned) this.root.scrollTop = this.root.scrollHeight;
  }
}
