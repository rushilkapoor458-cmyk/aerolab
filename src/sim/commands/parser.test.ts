import { describe, expect, it } from 'vitest';
import { parseAltitudeToken, parseCommandLine, tokenize } from './parser.js';
import { Command } from './types.js';

function commands(line: string): readonly Command[] {
  const result = parseCommandLine(line);
  if (!result.ok) throw new Error(`expected "${line}" to parse, got: ${result.error}`);
  return result.value.commands;
}

function error(line: string): string {
  const result = parseCommandLine(line);
  if (result.ok) throw new Error(`expected "${line}" to fail, but it parsed`);
  return result.error;
}

describe('tokenizer', () => {
  it('upper cases, splits on runs of space, and drops commas', () => {
    expect(tokenize('  aic101   tl 270,  d 50 ')).toEqual(['AIC101', 'TL', '270', 'D', '50']);
  });
});

describe('callsign', () => {
  it('is the first token', () => {
    const result = parseCommandLine('igo2145 h 090');
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value.callsign).toBe('IGO2145');
  });

  it('rejects something that is not a callsign', () => {
    expect(error('270 tl')).toMatch(/does not look like a callsign/);
  });

  it('complains when there is no instruction', () => {
    expect(error('AIC101')).toMatch(/no instruction/);
  });

  it('complains about an empty line', () => {
    expect(error('   ')).toMatch(/Nothing to send/);
  });
});

describe('headings', () => {
  it('accepts the full phraseology', () => {
    expect(commands('AIC101 turn left heading 270')).toEqual([
      { kind: 'heading', headingDeg: 270, turn: 'left' },
    ]);
    expect(commands('AIC101 turn right heading 090')).toEqual([
      { kind: 'heading', headingDeg: 90, turn: 'right' },
    ]);
    expect(commands('AIC101 fly heading 315')).toEqual([
      { kind: 'heading', headingDeg: 315, turn: 'shortest' },
    ]);
  });

  it('accepts the abbreviations', () => {
    expect(commands('AIC101 tl 270')).toEqual([{ kind: 'heading', headingDeg: 270, turn: 'left' }]);
    expect(commands('AIC101 tr 90')).toEqual([{ kind: 'heading', headingDeg: 90, turn: 'right' }]);
    expect(commands('AIC101 h 005')).toEqual([{ kind: 'heading', headingDeg: 5, turn: 'shortest' }]);
    expect(commands('AIC101 fh 180')).toEqual([{ kind: 'heading', headingDeg: 180, turn: 'shortest' }]);
  });

  it('normalises 360 to zero so the maths stays simple', () => {
    expect(commands('AIC101 h 360')).toEqual([{ kind: 'heading', headingDeg: 0, turn: 'shortest' }]);
  });

  it('refuses a heading that is not a heading', () => {
    expect(error('AIC101 tl 470')).toMatch(/Headings run from 001 to 360/);
    expect(error('AIC101 tl')).toMatch(/Expected a heading/);
    expect(error('AIC101 turn 270')).toMatch(/Turn which way/);
  });
});

describe('altitudes', () => {
  it('reads hundreds shorthand and plain feet the same way', () => {
    expect(parseAltitudeToken('50')).toBe(5000);
    expect(parseAltitudeToken('5000')).toBe(5000);
    expect(parseAltitudeToken('150')).toBe(15000);
    expect(parseAltitudeToken('FL150')).toBe(15000);
    expect(parseAltitudeToken('700')).toBe(700);
    expect(parseAltitudeToken('banana')).toBeNull();
  });

  it('accepts the full phraseology and the abbreviation', () => {
    expect(commands('AIC101 descend and maintain 5000')).toEqual([
      { kind: 'altitude', altitudeFt: 5000, sense: 'descend', expedite: false },
    ]);
    expect(commands('AIC101 d 50')).toEqual([
      { kind: 'altitude', altitudeFt: 5000, sense: 'descend', expedite: false },
    ]);
    expect(commands('AIC101 climb and maintain 9000')).toEqual([
      { kind: 'altitude', altitudeFt: 9000, sense: 'climb', expedite: false },
    ]);
    expect(commands('AIC101 maintain 7000')).toEqual([
      { kind: 'altitude', altitudeFt: 7000, sense: 'maintain', expedite: false },
    ]);
  });

  it('handles expedite', () => {
    expect(commands('AIC101 expedite climb through 8000')).toEqual([
      { kind: 'altitude', altitudeFt: 8000, sense: 'climb', expedite: true },
    ]);
    expect(commands('AIC101 ex d 40')).toEqual([
      { kind: 'altitude', altitudeFt: 4000, sense: 'descend', expedite: true },
    ]);
  });

  it('says what is wrong', () => {
    expect(error('AIC101 descend')).toMatch(/Expected an altitude/);
    expect(error('AIC101 d high')).toMatch(/is not an altitude/);
    expect(error('AIC101 expedite')).toMatch(/Expedite what/);
  });
});

describe('speeds', () => {
  it('accepts every form', () => {
    const expected = [{ kind: 'speed', speedKt: 210 }];
    expect(commands('AIC101 reduce speed to 210')).toEqual(expected);
    expect(commands('AIC101 increase speed to 210')).toEqual(expected);
    expect(commands('AIC101 speed 210')).toEqual(expected);
    expect(commands('AIC101 s 210')).toEqual(expected);
    expect(commands('AIC101 spd 210')).toEqual(expected);
  });

  it('cancels the restriction', () => {
    expect(commands('AIC101 cancel speed restriction')).toEqual([{ kind: 'speedCancel' }]);
    expect(commands('AIC101 resume normal speed')).toEqual([{ kind: 'speedCancel' }]);
  });

  it('explains a missing number', () => {
    expect(error('AIC101 s')).toMatch(/Expected a speed in knots/);
  });
});

describe('direct and squawk', () => {
  it('accepts every form of direct', () => {
    const expected = [{ kind: 'direct', fix: 'GUDUR' }];
    expect(commands('AIC101 proceed direct GUDUR')).toEqual(expected);
    expect(commands('AIC101 direct GUDUR')).toEqual(expected);
    expect(commands('AIC101 dct gudur')).toEqual(expected);
    expect(commands('AIC101 pd GUDUR')).toEqual(expected);
  });

  it('takes a four digit octal squawk', () => {
    expect(commands('AIC101 squawk 4271')).toEqual([{ kind: 'squawk', code: '4271' }]);
    expect(commands('AIC101 sq 4271')).toEqual([{ kind: 'squawk', code: '4271' }]);
    expect(error('AIC101 squawk 4281')).toMatch(/four digit code/);
    expect(error('AIC101 squawk 999')).toMatch(/four digit code/);
  });
});

describe('chaining', () => {
  it('takes several instructions in one transmission', () => {
    expect(commands('AIC101 tl 270 d 50 s 210')).toEqual([
      { kind: 'heading', headingDeg: 270, turn: 'left' },
      { kind: 'altitude', altitudeFt: 5000, sense: 'descend', expedite: false },
      { kind: 'speed', speedKt: 210 },
    ]);
  });

  it('takes the spoken form of the same transmission', () => {
    expect(commands('AIC101 turn left heading 270, descend and maintain 5000, reduce speed to 210')).toEqual([
      { kind: 'heading', headingDeg: 270, turn: 'left' },
      { kind: 'altitude', altitudeFt: 5000, sense: 'descend', expedite: false },
      { kind: 'speed', speedKt: 210 },
    ]);
  });

  it('mixes direct with a level and a speed', () => {
    expect(commands('IGO2145 dct TUMSA d 70 s 250')).toHaveLength(3);
  });
});

describe('unknown syntax', () => {
  it('names the offending word and lists what is understood', () => {
    const message = error('AIC101 wibble 270');
    expect(message).toMatch(/do not recognise "wibble"/);
    expect(message).toMatch(/turn left\/right heading/);
    expect(message).toMatch(/Press \? for the full reference/);
  });

  it('fails the whole line rather than half applying it', () => {
    const result = parseCommandLine('AIC101 tl 270 wibble');
    expect(result.ok).toBe(false);
  });
});
