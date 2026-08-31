import { describe, expect, it } from 'vitest';
import { parseCommandLine } from '../sim/commands/parser';
import { normaliseTranscript } from './voiceTranscript';

describe('normalising spoken clearances', () => {
  it('turns an airline name and spoken digits into a callsign', () => {
    expect(normaliseTranscript('air india one zero one descend and maintain five thousand'))
      .toBe('AIC101 descend and maintain 5000');
  });

  it('keeps air india express off air india', () => {
    expect(normaliseTranscript('air india express two four six fly heading two seven zero'))
      .toBe('AXB246 fly heading 270');
  });

  it('reads a heading as three separate digits, not a number', () => {
    expect(normaliseTranscript('indigo four one two turn left heading zero nine zero'))
      .toBe('IGO412 turn left heading 090');
  });

  it('expands whole thousands', () => {
    expect(normaliseTranscript('vistara seven one descend and maintain three thousand'))
      .toBe('VTI71 descend and maintain 3000');
  });

  it('expands thousands with hundreds', () => {
    expect(normaliseTranscript('indigo one one descend and maintain two thousand five hundred'))
      .toBe('IGO11 descend and maintain 2500');
  });

  it('folds a flight level', () => {
    expect(normaliseTranscript('emirates five one climb and maintain flight level one five zero'))
      .toBe('UAE51 climb and maintain FL150');
  });

  it('attaches a runway suffix to the number', () => {
    expect(normaliseTranscript('air india one zero one cleared ILS runway two nine right approach'))
      .toBe('AIC101 cleared ILS runway 29R approach');
  });

  it('does not mistake a turn direction for a runway suffix', () => {
    expect(normaliseTranscript('indigo four one two turn right heading three three zero'))
      .toBe('IGO412 turn right heading 330');
  });

  it('handles a runway suffix and a turn in the same transmission', () => {
    expect(normaliseTranscript('indigo four one two turn left heading two five zero cleared ILS runway two nine left approach'))
      .toBe('IGO412 turn left heading 250 cleared ILS runway 29L approach');
  });

  it('accepts the ICAO digit pronunciations', () => {
    expect(normaliseTranscript('spicejet niner tree reduce speed to one fife zero'))
      .toBe('SEJ93 reduce speed to 150');
  });

  it('joins a callsign the recogniser split apart', () => {
    expect(normaliseTranscript('AIC 101 go around')).toBe('AIC101 go around');
  });

  it('drops filler the recogniser picked up', () => {
    expect(normaliseTranscript('okay air india one zero one please go around'))
      .toBe('AIC101 go around');
  });

  it('strips units the parser does not want, but keeps knots', () => {
    // "feet" is not a parser token; "knots" is what tells a speed from a level.
    expect(normaliseTranscript('indigo one two descend and maintain five thousand feet'))
      .toBe('IGO12 descend and maintain 5000');
    expect(normaliseTranscript('indigo one two reduce speed to two one zero knots'))
      .toBe('IGO12 reduce speed to 210 knots');
  });

  it('keeps miles, which the speed-to-distance form needs', () => {
    expect(normaliseTranscript('air india one zero one maintain one six zero knots to four miles'))
      .toBe('AIC101 maintain 160 knots to 4 miles');
  });

  it('handles homophones the recogniser prefers', () => {
    // "to" for two, "for" for four, "ate" for eight, "oh" for zero.
    expect(normaliseTranscript('indigo to for ate proceed direct GUDUR'))
      .toBe('IGO248 proceed direct gudur');
  });

  it('returns empty for an empty utterance', () => {
    expect(normaliseTranscript('')).toBe('');
    expect(normaliseTranscript('   ')).toBe('');
  });

  it('ignores punctuation the recogniser adds', () => {
    expect(normaliseTranscript('Air India one zero one, descend and maintain five thousand.'))
      .toBe('AIC101 descend and maintain 5000');
  });
});

/**
 * The tests above pin the text the normaliser produces. These check the thing
 * that actually matters: that the real command parser accepts it. A spoken
 * clearance is only useful if it survives the whole path.
 */
describe('spoken clearances reach the parser', () => {
  const spoken = [
    'air india one zero one descend and maintain five thousand',
    'air india one zero one climb and maintain flight level one five zero',
    'indigo four one two turn left heading zero nine zero',
    'indigo four one two turn right heading three three zero',
    'vistara seven one reduce speed to two one zero',
    'air india one zero one cleared ILS runway two nine right approach',
    'air india one zero one maintain one six zero knots to four miles',
    'indigo four one two proceed direct GUDUR',
    'air india one zero one go around',
    'indigo four one two cleared for takeoff',
    'emirates five one hold at GUDUR as published',
    'air india one zero one say fuel remaining',
  ];

  for (const utterance of spoken) {
    it(`parses "${utterance}"`, () => {
      const line = normaliseTranscript(utterance);
      const result = parseCommandLine(line);
      // A failed parse carries the reason; surface it rather than a bare false.
      expect(result.ok ? null : result.error).toBeNull();
    });
  }
});
