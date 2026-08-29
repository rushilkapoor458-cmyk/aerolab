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
];

const PROCEDURES: readonly Row[] = [
  { keys: 'AIC101 cleared ILS runway 29 approach\nAIC101 ils 29', description: 'Clear it for the approach. It stays on your heading until the localiser captures — and only captures inside 18 NM, within 30° of the course, and inside the beam.' },
  { keys: 'AIC101 cancel approach', description: 'Take it off the approach and back onto vectors. Any heading, direct or hold does the same thing on its own.' },
  { keys: 'AIC101 go around\nAIC101 ga', description: 'Send it around. It climbs to the missed approach altitude on the runway heading.' },
  { keys: 'AIC101 hold at GUDUR as published\nAIC101 hold GUDUR', description: 'Enter the published racetrack: published inbound course, turn direction and leg time.' },
  { keys: 'AIC101 hold at GUDUR expect further clearance 1420\nAIC101 hold GUDUR efc 1420', description: 'The same, with an EFC time the crew read back.' },
  { keys: 'AIC101 descend via the arrival\nAIC101 dv', description: 'Fly the published STAR restrictions — each fix\u2019s altitude and speed — instead of level-by-level clearances.' },
];

const DEPARTURES: readonly Row[] = [
  { keys: 'IGO412 line up and wait runway 29\nIGO412 luw 29  ·  luw', description: 'Put a departure on the runway. Refused while the runway is occupied.' },
  { keys: 'IGO412 cleared for takeoff\nIGO412 takeoff  ·  cft', description: 'Send it. Lining up first is optional — a clearance to go implies it. It rolls, rotates at its own speed and climbs on its SID.' },
  { keys: 'IGO412 fly heading 270', description: 'Given to an aircraft still on the ground, this is a heading to fly after departure.' },
  { keys: 'IGO412 contact delhi control 127.9', description: 'Hand it on once it is climbing away. It counts as a departure when it leaves the sector.' },
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

const SESSION: readonly Row[] = [
  { keys: 'Scenarios', description: 'The button in the top right lists the five scenarios: tutorial, standard day, evening rush, runway change, and emergencies. Each runs from its own seed, so it plays out the same way every time.' },
  { keys: 'Strip bay', description: 'Arrivals and departures are kept apart, as on a real bay. Drag an arrival strip to set the order you intend to land them in; a strip whose number is amber is out of position against the order they will actually arrive in.' },
  { keys: 'NORDO', description: 'A radio failure. It squawks 7600, flies its last clearance, and answers nothing — your transmissions go out, they are simply not acknowledged.' },
  { keys: 'ENG', description: 'An engine failure. It squawks 7700, climbs at a fraction of its normal rate and will not accept more than 250 knots.' },
];

const SAFETY: readonly Row[] = [
  { keys: 'STCA', description: 'Short term conflict alert. Amber and dashed for a loss predicted within two minutes, red and solid the moment the minima are actually broken. The line between the pair is labelled with the current distance and vertical split.' },
  { keys: 'Separation minima', description: '3 NM and 1000 ft inside the terminal area; 5 NM as soon as either aircraft is more than 40 NM from the field.' },
  { keys: 'WAKE', description: 'Wake turbulence in trail on final: heavy behind heavy 4 NM, medium behind heavy 5, light behind heavy 6, light behind medium 5, and 8 behind a super. The full matrix is in src/data/wake.json.' },
  { keys: 'MSAW', description: 'Terrain. Amber while descending towards the minimum safe altitude, red below it. Suppressed once established on an approach, and silent where the grid publishes no terrain data.' },
  { keys: 'EXIT', description: 'An aircraft about to leave the sector, or already outside it, that you have not handed off.' },
  { keys: 'Score', description: 'The button in the top right opens the session report: movements, rate per hour, delay, fuel, and every minimum broken with the values at the closest point.' },
];

const APPROACH_NOTES: readonly Row[] = [
  { keys: 'A good intercept', description: 'Inside the intercept range, within 30° of the localiser course, and inside the beam. Miss any one and the aircraft flies straight through the centreline and tells you so.' },
  { keys: 'Glideslope from below', description: 'The slope is captured only when it comes down to the aircraft. Hold one high and it will stay high, then go around at the missed approach point.' },
  { keys: 'The gate at 1000 ft', description: 'Off the centreline, off the slope, too fast, or the runway still occupied, and the crew go around on their own.' },
  { keys: 'Runway occupancy', description: 'A landing aircraft holds the runway for just under a minute. Sequence tighter than that and the one behind goes around.' },
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
  { keys: 'AIC101 M ENG', description: 'Engine failure. Squawking 7700, climbing badly, capped at 250 knots.' },
  { keys: 'AIC101 M NORDO', description: 'Radio failure. Squawking 7600 and not answering.' },
  { keys: 'Amber block', description: 'A safety net caution names this aircraft — a predicted conflict, or terrain ahead.' },
  { keys: 'Red block', description: 'A safety net warning names it: separation, wake or terrain minima actually broken.' },
  { keys: '110↓090', description: 'Present altitude in hundreds of feet, the trend arrow, and the cleared altitude.' },
  { keys: '287 250 TUMSA', description: 'Groundspeed, assigned speed, and what it is steering by: a fix, H270 on a heading, HOLD GUDUR in the pattern, or the approach.' },
  { keys: '\u2192ILS29 \u2016ILS29 \u25bcILS29', description: 'Cleared for the approach on vectors, established on the localiser, and on the glidepath.' },
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
    '<h1>VIDP Approach — Delhi Director</h1>',
    '<p>An approach radar sector for Delhi: per-type performance and fuel, wind aloft, published arrivals and departures, holding, ILS approaches flown to a landing, the safety net, and five scenarios to run it in.</p>',
    '<h2>Instructions</h2>',
    table(COMMANDS),
    '<h2>Procedures</h2>',
    table(PROCEDURES),
    '<h2>Departures</h2>',
    table(DEPARTURES),
    '<h2>Keyboard</h2>',
    table(KEYS),
    '<h2>Mouse</h2>',
    table(MOUSE),
    '<h2>Flying the approach</h2>',
    table(APPROACH_NOTES),
    '<h2>The safety net</h2>',
    table(SAFETY),
    '<h2>The session</h2>',
    table(SESSION),
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
