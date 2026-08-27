import { describe, expect, it } from 'vitest';
import { parseAltitudeToken, parseClockTime, parseCommandLine, tokenize } from './parser.js';
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

describe('say fuel remaining', () => {
  it('accepts both forms', () => {
    expect(commands('AIC101 say fuel remaining')).toEqual([{ kind: 'sayFuel' }]);
    expect(commands('AIC101 say fuel')).toEqual([{ kind: 'sayFuel' }]);
  });

  it('explains anything else said after "say"', () => {
    expect(error('AIC101 say again')).toMatch(/say fuel remaining/);
  });
});

describe('contact', () => {
  it('takes a facility and a frequency', () => {
    expect(commands('AIC101 contact tower 118.1')).toEqual([
      { kind: 'contact', facility: 'tower', frequencyMhz: 118.1 },
    ]);
    expect(commands('AIC101 contact delhi control 127.9')).toEqual([
      { kind: 'contact', facility: 'delhi control', frequencyMhz: 127.9 },
    ]);
  });

  it('takes a bare frequency', () => {
    expect(commands('AIC101 ct 118.1')).toEqual([
      { kind: 'contact', facility: null, frequencyMhz: 118.1 },
    ]);
  });

  it('rejects a frequency outside the air band', () => {
    expect(error('AIC101 contact tower 108.1')).toMatch(/outside the air band/);
    expect(error('AIC101 contact tower 140.0')).toMatch(/outside the air band/);
  });

  it('says what is missing when there is no frequency', () => {
    expect(error('AIC101 contact tower')).toMatch(/Contact whom, and on what frequency/);
  });

  it('does not swallow the next instruction into the facility name', () => {
    expect(error('AIC101 contact tl 270')).toMatch(/Contact whom/);
  });
});

describe('approaches', () => {
  it('accepts the full clearance and the shorthand', () => {
    const expected = [{ kind: 'approach', runway: '29' }];
    expect(commands('AIC101 cleared ILS runway 29 approach')).toEqual(expected);
    expect(commands('AIC101 cleared ils 29')).toEqual(expected);
    expect(commands('AIC101 ils 29')).toEqual(expected);
    expect(commands('AIC101 ils rwy 29')).toEqual(expected);
  });

  it('pads a single digit runway', () => {
    expect(commands('AIC101 ils 9')).toEqual([{ kind: 'approach', runway: '09' }]);
  });

  it('takes a parallel runway designator', () => {
    expect(commands('AIC101 ils 29L')).toEqual([{ kind: 'approach', runway: '29L' }]);
  });

  it('explains a missing runway', () => {
    expect(error('AIC101 ils')).toMatch(/Which runway/);
    expect(error('AIC101 cleared visual 29')).toMatch(/cleared ILS runway 29 approach/);
  });

  it('cancels an approach and goes around', () => {
    expect(commands('AIC101 cancel approach')).toEqual([{ kind: 'cancelApproach' }]);
    expect(commands('AIC101 go around')).toEqual([{ kind: 'goAround' }]);
    expect(commands('AIC101 ga')).toEqual([{ kind: 'goAround' }]);
    expect(error('AIC101 go home')).toMatch(/instruction is "go around"/);
  });
});

describe('holding', () => {
  it('accepts the published hold in every form', () => {
    const expected = [{ kind: 'hold', fix: 'GUDUR', efcTimeSec: null }];
    expect(commands('AIC101 hold at GUDUR as published')).toEqual(expected);
    expect(commands('AIC101 hold at GUDUR')).toEqual(expected);
    expect(commands('AIC101 hold GUDUR')).toEqual(expected);
  });

  it('takes an expect further clearance time', () => {
    expect(commands('AIC101 hold at GUDUR as published expect further clearance 1420')).toEqual([
      { kind: 'hold', fix: 'GUDUR', efcTimeSec: 14 * 3600 + 20 * 60 },
    ]);
    expect(commands('AIC101 hold GUDUR efc 0905')).toEqual([
      { kind: 'hold', fix: 'GUDUR', efcTimeSec: 9 * 3600 + 5 * 60 },
    ]);
  });

  it('rejects a time that is not a time', () => {
    expect(parseClockTime('1420')).toBe(14 * 3600 + 20 * 60);
    expect(parseClockTime('2500')).toBeNull();
    expect(parseClockTime('1265')).toBeNull();
    expect(parseClockTime('142')).toBeNull();
    expect(error('AIC101 hold GUDUR efc 9999')).toMatch(/is not a time/);
    expect(error('AIC101 hold GUDUR efc')).toMatch(/at what time/);
  });

  it('explains a missing fix', () => {
    expect(error('AIC101 hold')).toMatch(/Hold where/);
  });
});

describe('descend via', () => {
  it('is not confused with a descent to a level', () => {
    expect(commands('AIC101 descend via the arrival')).toEqual([{ kind: 'descendVia' }]);
    expect(commands('AIC101 descend via')).toEqual([{ kind: 'descendVia' }]);
    expect(commands('AIC101 dv')).toEqual([{ kind: 'descendVia' }]);
    expect(commands('AIC101 d 50')).toEqual([
      { kind: 'altitude', altitudeFt: 5000, sense: 'descend', expedite: false },
    ]);
  });
});

describe('unknown syntax', () => {
  it('names the offending word and lists what is understood', () => {
    const message = error('AIC101 wibble 270');
    expect(message).toMatch(/do not recognise "wibble"/);
    expect(message).toMatch(/turn left\/right heading/);
    expect(message).toMatch(/say fuel/);
    expect(message).toMatch(/cleared ILS, hold, go around/);
    expect(message).toMatch(/Press \? for the full reference/);
  });

  it('fails the whole line rather than half applying it', () => {
    const result = parseCommandLine('AIC101 tl 270 wibble');
    expect(result.ok).toBe(false);
  });
});
