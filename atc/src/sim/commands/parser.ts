/**
 * Command line parser.
 *
 * Accepts full phraseology and the abbreviated forms controllers actually
 * type, and chains as many instructions onto one callsign as you like:
 *
 *   AIC101 turn left heading 270 descend and maintain 5000 reduce speed to 210
 *   AIC101 tl 270 d 50 s 210
 *
 * Every failure returns a message naming what was wrong and showing a
 * working example. Nothing fails silently.
 */

import { normalizeDeg } from '../geo.js';
import { Command, ParseResult } from './types.js';

/** Words that carry no meaning of their own and may appear anywhere. */
const FILLER = new Set(['AND', 'TO', 'AT', 'A', 'THE', 'THEN', 'PLEASE']);

/** Words that may follow a climb or descend before the altitude. */
const VERTICAL_FILLER = new Set(['AND', 'TO', 'MAINTAIN', 'THROUGH', 'LEVEL']);

const CALLSIGN_RE = /^[A-Z][A-Z0-9]{1,7}$/;

/** Words that begin an instruction, so a facility name cannot swallow them. */
const INSTRUCTION_WORDS = new Set([
  'TURN', 'TL', 'TR', 'FLY', 'FH', 'HEADING', 'HDG', 'H',
  'CLIMB', 'C', 'DESCEND', 'DESCENT', 'D', 'MAINTAIN', 'ALT', 'M',
  'EXPEDITE', 'EX', 'REDUCE', 'INCREASE', 'SPEED', 'SPD', 'S',
  'CANCEL', 'RESUME', 'PROCEED', 'DIRECT', 'DCT', 'PD',
  'SQUAWK', 'SQ', 'SAY', 'CONTACT', 'CT',
  'CLEARED', 'ILS', 'HOLD', 'GO', 'GA', 'DV',
  'LINE', 'LUW', 'LINEUP', 'TAKEOFF', 'CFT', 'MIN', 'MINIMUM',
]);

class TokenCursor {
  private index = 0;

  constructor(private readonly tokens: readonly string[]) {}

  get done(): boolean {
    return this.index >= this.tokens.length;
  }

  peek(offset = 0): string | undefined {
    return this.tokens[this.index + offset];
  }

  next(): string | undefined {
    const t = this.tokens[this.index];
    this.index += 1;
    return t;
  }

  /** Consume the token if it is one of `words`; report whether it was. */
  accept(...words: readonly string[]): boolean {
    const t = this.peek();
    if (t !== undefined && words.includes(t)) {
      this.index += 1;
      return true;
    }
    return false;
  }

  /** Consume any run of tokens drawn from `set`. */
  skipAll(set: ReadonlySet<string>): void {
    while (!this.done) {
      const t = this.peek();
      if (t === undefined || !set.has(t)) return;
      this.index += 1;
    }
  }
}

export function tokenize(line: string): string[] {
  return line
    .toUpperCase()
    .replace(/[,;]/g, ' ')
    .split(/\s+/)
    .filter((t) => t.length > 0);
}

export function parseCommandLine(line: string): ParseResult {
  const tokens = tokenize(line);
  if (tokens.length === 0) return fail('Nothing to send. Type a callsign followed by an instruction.');

  const callsign = tokens[0];
  if (callsign === undefined || !CALLSIGN_RE.test(callsign)) {
    return fail(
      `"${tokens[0] ?? ''}" does not look like a callsign. Start with the aircraft, for example "AIC101 tl 270".`,
    );
  }

  const cursor = new TokenCursor(tokens.slice(1));
  const commands: Command[] = [];

  while (!cursor.done) {
    cursor.skipAll(FILLER);
    if (cursor.done) break;
    const result = parseOne(cursor);
    if (!result.ok) return result;
    commands.push(result.command);
  }

  if (commands.length === 0) {
    return fail(`${callsign} received, but there was no instruction. Try "${callsign} tl 270".`);
  }
  return { ok: true, value: { callsign, commands } };
}

type OneResult = { ok: true; command: Command } | { ok: false; error: string };

function parseOne(cursor: TokenCursor): OneResult {
  const word = cursor.next();
  if (word === undefined) return fail('Unexpected end of instruction.');

  switch (word) {
    case 'TURN': {
      const side = cursor.next();
      if (side === 'LEFT' || side === 'L') return parseHeading(cursor, 'left');
      if (side === 'RIGHT' || side === 'R') return parseHeading(cursor, 'right');
      return fail('Turn which way? Use "turn left heading 270" or "turn right heading 270".');
    }
    case 'TL':
      return parseHeading(cursor, 'left');
    case 'TR':
      return parseHeading(cursor, 'right');
    case 'FLY':
    case 'FH':
    case 'HEADING':
    case 'HDG':
    case 'H':
      return parseHeading(cursor, 'shortest');

    case 'CLIMB':
    case 'C':
      return parseAltitude(cursor, 'climb', false);
    case 'DESCEND':
    case 'DESCENT':
    case 'D': {
      // "descend via the arrival" is a different instruction from "descend to".
      if (cursor.accept('VIA')) {
        cursor.accept('THE');
        cursor.accept('ARRIVAL', 'STAR');
        return { ok: true, command: { kind: 'descendVia' } };
      }
      return parseAltitude(cursor, 'descend', false);
    }
    case 'DV':
      cursor.accept('THE');
      cursor.accept('ARRIVAL', 'STAR');
      return { ok: true, command: { kind: 'descendVia' } };
    case 'MAINTAIN':
    case 'ALT':
    case 'M': {
      // "maintain 160 knots" is a speed; "maintain 6000" is a level.
      const value = cursor.peek();
      const unit = cursor.peek(1);
      if (value !== undefined && /^\d{2,3}$/.test(value) && unit !== undefined && SPEED_UNITS.has(unit)) {
        return parseSpeed(cursor);
      }
      return parseAltitude(cursor, 'maintain', false);
    }
    case 'EXPEDITE':
    case 'EX': {
      const what = cursor.next();
      if (what === 'CLIMB' || what === 'C') return parseAltitude(cursor, 'climb', true);
      if (what === 'DESCENT' || what === 'DESCEND' || what === 'D') {
        return parseAltitude(cursor, 'descend', true);
      }
      return fail('Expedite what? Use "expedite climb through 8000" or "expedite descent through 5000".');
    }

    case 'REDUCE':
    case 'INCREASE': {
      cursor.accept('SPEED');
      cursor.accept('TO');
      if (cursor.accept('MINIMUM', 'MIN')) {
        cursor.accept('APPROACH');
        cursor.accept('SPEED');
        return { ok: true, command: { kind: 'minimumApproachSpeed' } };
      }
      return parseSpeed(cursor);
    }
    case 'MIN':
    case 'MINIMUM':
      cursor.accept('APPROACH');
      cursor.accept('SPEED');
      return { ok: true, command: { kind: 'minimumApproachSpeed' } };
    case 'SPEED':
    case 'SPD':
    case 'S':
      return parseSpeed(cursor);
    case 'CANCEL': {
      if (cursor.accept('SPEED')) {
        cursor.accept('RESTRICTION', 'RESTRICTIONS');
        return { ok: true, command: { kind: 'speedCancel' } };
      }
      if (cursor.accept('APPROACH')) return { ok: true, command: { kind: 'cancelApproach' } };
      return fail('Cancel what? Try "cancel speed restriction" or "cancel approach".');
    }
    case 'RESUME': {
      cursor.accept('NORMAL');
      if (cursor.accept('SPEED')) return { ok: true, command: { kind: 'speedCancel' } };
      return fail('Resume what? Use "resume normal speed".');
    }

    case 'PROCEED': {
      if (!cursor.accept('DIRECT', 'DCT')) {
        return fail('Proceed how? Use "proceed direct GUDUR".');
      }
      return parseDirect(cursor);
    }
    case 'DIRECT':
    case 'DCT':
    case 'PD':
      return parseDirect(cursor);

    case 'SQUAWK':
    case 'SQ': {
      const code = cursor.next();
      if (code === undefined || !/^[0-7]{4}$/.test(code)) {
        return fail(`Squawk needs a four digit code from 0 to 7, for example "squawk 4271".`);
      }
      return { ok: true, command: { kind: 'squawk', code } };
    }

    case 'SAY': {
      if (cursor.accept('FUEL')) {
        cursor.accept('REMAINING');
        return { ok: true, command: { kind: 'sayFuel' } };
      }
      return fail('Say what? The only request available is "say fuel remaining".');
    }

    case 'CONTACT':
    case 'CT':
      return parseContact(cursor);

    case 'CLEARED': {
      if (cursor.accept('TO')) {
        if (cursor.accept('LAND')) {
          return fail('Landing clearance is the tower\u2019s. Clear it for the approach instead: "cleared ILS runway 29 approach".');
        }
        return fail('Cleared to what?');
      }
      const forTakeoff = cursor.peek() === 'FOR' && cursor.peek(1) === 'TAKEOFF';
      if (forTakeoff) {
        cursor.next();
        cursor.next();
        cursor.accept('RUNWAY', 'RWY');
        if (cursor.peek() !== undefined && RUNWAY_RE.test(cursor.peek() ?? '')) cursor.next();
        return { ok: true, command: { kind: 'takeoff' } };
      }
      cursor.accept('FOR');
      if (!cursor.accept('ILS')) {
        return fail('Cleared for what? Either "cleared ILS runway 29 approach" or "cleared for takeoff".');
      }
      return parseApproach(cursor);
    }
    case 'ILS':
      return parseApproach(cursor);

    case 'HOLD':
      return parseHold(cursor);

    case 'LINE': {
      if (!cursor.accept('UP')) return fail('Line up? The instruction is "line up and wait runway 29".');
      cursor.accept('AND');
      cursor.accept('WAIT');
      return parseLineUp(cursor);
    }
    case 'LUW':
    case 'LINEUP':
      return parseLineUp(cursor);

    case 'TAKEOFF':
    case 'CFT':
      return { ok: true, command: { kind: 'takeoff' } };

    case 'GO': {
      if (cursor.accept('AROUND')) return { ok: true, command: { kind: 'goAround' } };
      return fail('Go where? The instruction is "go around".');
    }
    case 'GA':
      return { ok: true, command: { kind: 'goAround' } };

    default:
      return fail(
        `I do not recognise "${word.toLowerCase()}". The simulator understands: turn left/right heading, fly heading, ` +
          `climb, descend, descend via, maintain, expedite, speed, minimum approach speed, ` +
          `cancel speed restriction, proceed direct, ` +
          `cleared ILS, hold, go around, line up and wait, cleared for takeoff, squawk, say fuel ` +
          `and contact. Press ? for the full reference.`,
      );
  }
}

function parseHeading(cursor: TokenCursor, turn: 'left' | 'right' | 'shortest'): OneResult {
  cursor.accept('HEADING', 'HDG', 'ON', 'TO');
  const token = cursor.next();
  if (token === undefined || !/^\d{1,3}$/.test(token)) {
    const example = turn === 'left' ? 'tl 270' : turn === 'right' ? 'tr 090' : 'fh 270';
    return fail(`Expected a heading of up to three digits, for example "${example}".`);
  }
  const value = Number(token);
  if (value > 360) return fail(`${value} is not a heading. Headings run from 001 to 360.`);
  return { ok: true, command: { kind: 'heading', headingDeg: normalizeDeg(value), turn } };
}

/**
 * Altitudes accept both the spoken form and the shorthand: 5000 and 50 both
 * mean five thousand feet, FL150 means 15,000 ft. Anything at or below 600 is
 * read as hundreds of feet, which is how controllers abbreviate.
 */
export function parseAltitudeToken(token: string): number | null {
  const fl = /^FL(\d{2,3})$/.exec(token);
  if (fl !== null && fl[1] !== undefined) return Number(fl[1]) * 100;
  if (!/^\d{1,5}$/.test(token)) return null;
  const value = Number(token);
  if (value === 0) return 0;
  return value <= 600 ? value * 100 : value;
}

function parseAltitude(
  cursor: TokenCursor,
  sense: 'climb' | 'descend' | 'maintain',
  expedite: boolean,
): OneResult {
  cursor.skipAll(VERTICAL_FILLER);
  const token = cursor.next();
  if (token === undefined) {
    return fail(`Expected an altitude after "${sense}", for example "${sense === 'climb' ? 'c 90' : 'd 50'}" or "${sense} and maintain 5000".`);
  }
  const altitude = parseAltitudeToken(token);
  if (altitude === null) {
    return fail(`"${token.toLowerCase()}" is not an altitude. Use 5000, 50 or FL150.`);
  }
  return { ok: true, command: { kind: 'altitude', altitudeFt: altitude, sense, expedite } };
}

/** Words meaning knots, so a speed can be told apart from a level. */
const SPEED_UNITS = new Set(['KNOTS', 'KNOT', 'KTS', 'KT']);

/** The furthest out an assigned approach speed may be released. */
export const MAX_SPEED_RELEASE_NM = 20;

/**
 * `s 210`, `reduce speed to 210`, and the form that does the real work on
 * final: `maintain 160 knots to 4 miles`, or `s 160 to 4`.
 */
function parseSpeed(cursor: TokenCursor): OneResult {
  cursor.skipAll(new Set(['SPEED', 'TO', 'AT']));
  const token = cursor.next();
  if (token === undefined || !/^\d{2,3}$/.test(token)) {
    return fail('Expected a speed in knots, for example "s 210" or "reduce speed to 210".');
  }
  cursor.accept(...SPEED_UNITS);

  let releaseDistanceNm: number | null = null;
  if (cursor.peek() === 'TO' && /^\d{1,2}$/.test(cursor.peek(1) ?? '')) {
    cursor.next();
    releaseDistanceNm = Number(cursor.next());
    cursor.accept('MILES', 'MILE', 'NM', 'DME', 'TRACK');
    if (releaseDistanceNm < 1 || releaseDistanceNm > MAX_SPEED_RELEASE_NM) {
      return fail(
        `A speed can only be held to between 1 and ${MAX_SPEED_RELEASE_NM} miles, for example "s 160 to 4".`,
      );
    }
  }

  return { ok: true, command: { kind: 'speed', speedKt: Number(token), releaseDistanceNm } };
}

function parseDirect(cursor: TokenCursor): OneResult {
  const token = cursor.next();
  if (token === undefined || !/^[A-Z]{2,5}$/.test(token)) {
    return fail('Expected a fix name after direct, for example "dct GUDUR".');
  }
  return { ok: true, command: { kind: 'direct', fix: token } };
}

const RUNWAY_RE = /^\d{1,2}[LCR]?$/;

/** `cleared ILS runway 29 approach`, `cleared ils 29`, `ils 29`. */
function parseApproach(cursor: TokenCursor): OneResult {
  cursor.accept('RUNWAY', 'RWY');
  const token = cursor.next();
  if (token === undefined || !RUNWAY_RE.test(token)) {
    return fail('Which runway? For example "cleared ILS runway 29 approach" or "ils 29".');
  }
  cursor.accept('APPROACH');
  const ident = token.length === 1 ? `0${token}` : token;
  return { ok: true, command: { kind: 'approach', runway: ident } };
}

/** `line up and wait runway 29`, `luw 29`, or just `luw`. */
function parseLineUp(cursor: TokenCursor): OneResult {
  cursor.accept('RUNWAY', 'RWY');
  const token = cursor.peek();
  if (token !== undefined && RUNWAY_RE.test(token)) {
    cursor.next();
    const ident = token.length === 1 ? `0${token}` : token;
    return { ok: true, command: { kind: 'lineUp', runway: ident } };
  }
  return { ok: true, command: { kind: 'lineUp', runway: null } };
}

/** A four figure clock time, `1420`, as seconds since midnight. */
export function parseClockTime(token: string): number | null {
  if (!/^\d{4}$/.test(token)) return null;
  const hours = Number(token.slice(0, 2));
  const minutes = Number(token.slice(2));
  if (hours > 23 || minutes > 59) return null;
  return hours * 3600 + minutes * 60;
}

/** `hold at GUDUR as published, expect further clearance 1420`. */
function parseHold(cursor: TokenCursor): OneResult {
  cursor.accept('AT', 'OVER');
  const fix = cursor.next();
  if (fix === undefined || !/^[A-Z]{2,5}$/.test(fix)) {
    return fail('Hold where? For example "hold at GUDUR as published".');
  }
  cursor.accept('AS');
  cursor.accept('PUBLISHED');

  let efcTimeSec: number | null = null;
  if (cursor.accept('EXPECT', 'EFC')) {
    cursor.accept('FURTHER');
    cursor.accept('CLEARANCE');
    const token = cursor.next();
    if (token === undefined) {
      return fail('Expect further clearance at what time? For example "expect further clearance 1420".');
    }
    efcTimeSec = parseClockTime(token);
    if (efcTimeSec === null) {
      return fail(`"${token}" is not a time. Give it as four figures, for example 1420.`);
    }
  }
  return { ok: true, command: { kind: 'hold', fix, efcTimeSec } };
}

/** The civil VHF air band, in megahertz. */
export const VHF_MIN_MHZ = 118.0;
export const VHF_MAX_MHZ = 136.975;

function isFrequency(token: string): boolean {
  return /^\d{3}(\.\d{1,3})?$/.test(token);
}

/**
 * `contact tower 118.1`, `contact delhi control 127.9`, `ct 118.1`. Anything
 * before the frequency is the facility name, spoken back as given.
 */
function parseContact(cursor: TokenCursor): OneResult {
  const words: string[] = [];
  let frequency: number | null = null;

  while (!cursor.done) {
    const token = cursor.peek();
    if (token === undefined) break;
    if (isFrequency(token)) {
      cursor.next();
      frequency = Number(token);
      break;
    }
    if (!/^[A-Z]+$/.test(token)) break;
    // Stop before a word that starts the next instruction in a chained line.
    if (INSTRUCTION_WORDS.has(token)) break;
    cursor.next();
    words.push(token);
  }

  if (frequency === null) {
    return fail('Contact whom, and on what frequency? For example "contact tower 118.1".');
  }
  if (frequency < VHF_MIN_MHZ || frequency > VHF_MAX_MHZ) {
    return fail(
      `${frequency.toFixed(3)} is outside the air band (${VHF_MIN_MHZ.toFixed(1)} to ${VHF_MAX_MHZ.toFixed(3)} MHz).`,
    );
  }
  return {
    ok: true,
    command: {
      kind: 'contact',
      facility: words.length === 0 ? null : words.join(' ').toLowerCase(),
      frequencyMhz: frequency,
    },
  };
}

function fail(error: string): { ok: false; error: string } {
  return { ok: false, error };
}
