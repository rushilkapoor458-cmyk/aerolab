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
    case 'D':
      return parseAltitude(cursor, 'descend', false);
    case 'MAINTAIN':
    case 'ALT':
    case 'M':
      return parseAltitude(cursor, 'maintain', false);
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
      return parseSpeed(cursor);
    }
    case 'SPEED':
    case 'SPD':
    case 'S':
      return parseSpeed(cursor);
    case 'CANCEL': {
      if (cursor.accept('SPEED')) {
        cursor.accept('RESTRICTION', 'RESTRICTIONS');
        return { ok: true, command: { kind: 'speedCancel' } };
      }
      return fail('Cancel what? The only cancellation available is "cancel speed restriction".');
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

    default:
      return fail(
        `I do not recognise "${word.toLowerCase()}". Milestone 1 understands: turn left/right heading, fly heading, ` +
          `climb, descend, maintain, expedite, speed, cancel speed restriction, proceed direct and squawk. ` +
          `Press ? for the full reference.`,
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

function parseSpeed(cursor: TokenCursor): OneResult {
  cursor.skipAll(new Set(['SPEED', 'TO', 'AT']));
  const token = cursor.next();
  if (token === undefined || !/^\d{2,3}$/.test(token)) {
    return fail('Expected a speed in knots, for example "s 210" or "reduce speed to 210".');
  }
  return { ok: true, command: { kind: 'speed', speedKt: Number(token) } };
}

function parseDirect(cursor: TokenCursor): OneResult {
  const token = cursor.next();
  if (token === undefined || !/^[A-Z]{2,5}$/.test(token)) {
    return fail('Expected a fix name after direct, for example "dct GUDUR".');
  }
  return { ok: true, command: { kind: 'direct', fix: token } };
}

function fail(error: string): { ok: false; error: string } {
  return { ok: false, error };
}
