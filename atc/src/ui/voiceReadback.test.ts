import { describe, expect, it } from 'vitest';
import { spoken } from './voice';

/**
 * The reverse of the transcript normaliser: written phraseology going back
 * out as radio speech. A synthesiser reads "29R" as "twenty-nine R", which is
 * not what a pilot says.
 */
describe('speaking a readback aloud', () => {
  it('reads a runway as digits and a side', () => {
    expect(spoken('cleared ILS runway 29R approach'))
      .toBe('cleared ILS runway 2 niner right approach');
  });

  it('reads 29L as left', () => {
    expect(spoken('landing runway 29L')).toBe('landing runway 2 niner left');
  });

  it('reads a flight level digit by digit', () => {
    expect(spoken('climb and maintain FL150')).toBe('climb and maintain flight level 1 5 0');
  });

  it('reads a heading digit by digit', () => {
    expect(spoken('fly heading 270')).toBe('fly heading 2 7 0');
  });

  it('uses niner for nine', () => {
    expect(spoken('fly heading 090')).toBe('fly heading 0 niner 0');
  });

  it('keeps a whole-thousand altitude as a number', () => {
    expect(spoken('descend and maintain 5000')).toBe('descend and maintain 5000');
  });

  it('splits a squawk into digits', () => {
    expect(spoken('squawk 4271')).toBe('squawk 4 2 7 1');
  });

  it('leaves text with no numbers alone', () => {
    expect(spoken('going around')).toBe('going around');
  });
});
