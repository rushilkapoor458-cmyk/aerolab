/** The in-game help overlay, bound to the `?` key. */

interface Row {
  readonly keys: string;
  readonly description: string;
}

const COMMANDS: readonly Row[] = [
  { keys: 'AIC101 turn left heading 270\nAIC101 tl 270', description: 'Turn left onto a magnetic heading. The long way round if that is the side you named.' },
  { keys: 'AIC101 turn right heading 090\nAIC101 tr 090', description: 'Turn right onto a magnetic heading.' },
  { keys: 'AIC101 fly heading 270\nAIC101 fh 270  ·  h 270', description: 'Take up a heading the short way round.' },
  { keys: 'AIC101 descend and maintain 5000\nAIC101 d 50  ·  d 5000', description: 'Descend. Numbers of 600 or less are read as hundreds of feet, so 50 is 5,000 ft.' },
  { keys: 'AIC101 climb and maintain 9000\nAIC101 c 90  ·  c FL150', description: 'Climb.' },
  { keys: 'AIC101 maintain 7000\nAIC101 m 70', description: 'Stop a climb or descent at a level.' },
  { keys: 'AIC101 expedite climb through 8000\nAIC101 ex c 80', description: 'Best rate through a level. Also expedite descent.' },
  { keys: 'AIC101 reduce speed to 210\nAIC101 s 210  ·  spd 210', description: 'Assign an indicated airspeed.' },
  { keys: 'AIC101 cancel speed restriction\nAIC101 resume normal speed', description: 'Release the 250 kt below 10,000 ft rule for that aircraft.' },
  { keys: 'AIC101 proceed direct GUDUR\nAIC101 dct GUDUR  ·  pd GUDUR', description: 'Track to a published fix, then continue on the rest of its route.' },
  { keys: 'AIC101 squawk 4271\nAIC101 sq 4271', description: 'Assign a transponder code. Refused while an emergency squawk is set.' },
  { keys: 'AIC101 say fuel remaining\nAIC101 say fuel', description: 'Ask for fuel on board. The crew answer in kilos and minutes.' },
  { keys: 'AIC101 contact tower 118.1\nAIC101 ct 118.1', description: 'Hand the aircraft off. It leaves your frequency and drops off the scope once it is out of the sector.' },
  { keys: 'AIC101 tl 270 d 50 s 210', description: 'Chain as many instructions as you like onto one callsign.' },
];

const KEYS: readonly Row[] = [
  { keys: 'Tab', description: 'Complete the callsign. Press again to cycle through the aircraft that match.' },
  { keys: '↑ / ↓', description: 'Walk back and forth through what you have already sent.' },
  { keys: 'Enter', description: 'Transmit. A line that will not parse stays in the box with the reason underneath.' },
  { keys: 'Space', description: 'Pause and resume, when the command line is empty.' },
  { keys: '?', description: 'This overlay, when the command line is empty. Escape or ? closes it.' },
  { keys: 'Escape', description: 'Clear the command line.' },
];

const MODEL: readonly Row[] = [
  { keys: 'Performance', description: 'Every type flies its own profile: climb and descent rates fall off with altitude and change with mass, and each has its own speed envelope and acceleration limits.' },
  { keys: 'Wind aloft', description: 'The wind veers and strengthens with height. An aircraft at 13,000 ft feels a different wind from one on base leg — press WX to change either end of the profile live.' },
  { keys: 'Down and slow', description: 'An aircraft asked to descend and slow at the same time will do neither at full rate, and will say so through its rate of descent.' },
  { keys: 'Fuel', description: 'Burn is per phase of flight. Under 30 minutes the crew advise minimum fuel; under 15 they declare an emergency and squawk 7700.' },
];

const MOUSE: readonly Row[] = [
  { keys: 'Click a target', description: 'Select it, draw its route, and put its callsign in the command line.' },
  { keys: 'Click empty scope', description: 'Deselect.' },
  { keys: 'Drag from a target', description: 'Measure range and magnetic bearing to any point.' },
  { keys: 'Drag the scope', description: 'Pan.' },
  { keys: 'Scroll wheel', description: 'Zoom about the pointer.' },
];

const BLOCK: readonly Row[] = [
  { keys: 'AIC101 M', description: 'Callsign and wake turbulence category (L, M, H, J).' },
  { keys: 'AIC101 M MIN', description: 'Amber: minimum fuel advised. The crew can accept no undue delay.' },
  { keys: 'AIC101 M EMG', description: 'Red: emergency declared, squawking 7700. It wants priority.' },
  { keys: 'AIC101 M HO', description: 'Dimmed: handed off to another frequency and no longer taking your instructions.' },
  { keys: '110↓090', description: 'Present altitude in hundreds of feet, the trend arrow, and the cleared altitude.' },
  { keys: '287 250 TUMSA', description: 'Groundspeed, assigned speed, and the fix being tracked — or H270 when on a heading.' },
];

export class HelpOverlay {
  private open = false;

  constructor(private readonly root: HTMLElement) {
    this.root.innerHTML = render();
    this.root.hidden = true;
    this.root.addEventListener('click', () => this.hide());
  }

  toggle(): void {
    this.open ? this.hide() : this.show();
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
}

function table(rows: readonly Row[]): string {
  const body = rows
    .map(
      (row) =>
        `<tr><td class="k">${escapeHtml(row.keys).replace(/\n/g, '<br />')}</td><td class="d">${escapeHtml(row.description)}</td></tr>`,
    )
    .join('');
  return `<table><tbody>${body}</tbody></table>`;
}

function render(): string {
  return [
    '<h1>Delhi Approach — milestone 2</h1>',
    '<p>Radar scope, the full flight model with per-type performance and fuel, wind aloft, and the basic command set. Approaches, sequencing, conflict alerting and scenarios arrive in the milestones that follow.</p>',
    '<h2>Instructions</h2>',
    table(COMMANDS),
    '<h2>Keyboard</h2>',
    table(KEYS),
    '<h2>Mouse</h2>',
    table(MOUSE),
    '<h2>What the aircraft are doing</h2>',
    table(MODEL),
    '<h2>Reading a data block</h2>',
    table(BLOCK),
    '<p class="close">Click anywhere, or press ? or Escape, to close.</p>',
  ].join('');
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
