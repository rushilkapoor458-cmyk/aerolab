import { describe, expect, it } from 'vitest';
import { makeTestAircraft } from '../sim/testAircraft.js';
import { StripRow, orderArrivals, stripState } from './strips.js';

function row(id: string, rangeNm: number): StripRow {
  return {
    id,
    callsign: id.toUpperCase(),
    type: 'A320',
    wake: 'M',
    state: 'heading 270',
    rangeNm,
    altitudeFt: 7000,
    speedKt: 250,
    alert: 'none',
    onApproach: false,
    holding: false,
  };
}

describe('the intended sequence', () => {
  it('is range order until anything is dragged', () => {
    const rows = [row('a', 30), row('b', 10), row('c', 20)];
    expect(orderArrivals(rows, []).map((r) => r.id)).toEqual(['b', 'c', 'a']);
  });

  it('keeps the order the controller put things in', () => {
    const rows = [row('a', 30), row('b', 10), row('c', 20)];
    expect(orderArrivals(rows, ['a', 'b', 'c']).map((r) => r.id)).toEqual(['a', 'b', 'c']);
  });

  it('adds new arrivals behind the ones already sequenced, in range order', () => {
    const rows = [row('a', 30), row('b', 10), row('new1', 5), row('new2', 40)];
    expect(orderArrivals(rows, ['a', 'b']).map((r) => r.id)).toEqual(['a', 'b', 'new1', 'new2']);
  });

  it('forgets aircraft that are no longer there', () => {
    const rows = [row('a', 30)];
    expect(orderArrivals(rows, ['gone', 'a']).map((r) => r.id)).toEqual(['a']);
  });

  it('does not lose or duplicate anything', () => {
    const rows = [row('a', 30), row('b', 10), row('c', 20), row('d', 15)];
    const ordered = orderArrivals(rows, ['c', 'a']);
    expect(ordered).toHaveLength(4);
    expect(new Set(ordered.map((r) => r.id)).size).toBe(4);
  });
});

describe('what a strip says', () => {
  it('reports the ground states', () => {
    expect(stripState(makeTestAircraft({ ground: 'queue' }))).toBe('holding point');
    expect(stripState(makeTestAircraft({ ground: 'lineup', departureRunway: '29' }))).toBe(
      'lined up 29',
    );
    expect(stripState(makeTestAircraft({ ground: 'takeoff' }))).toBe('rolling');
  });

  it('flags a radio failure above everything else', () => {
    const ac = makeTestAircraft({ emergency: 'radio' });
    ac.clearance.lateralMode = 'direct';
    ac.clearance.directFix = 'GUDUR';
    expect(stripState(ac)).toMatch(/no radio/);
  });

  it('reports the stage of an approach', () => {
    const base = {
      runway: '29',
      ident: 'ILS29',
      localiserCaptured: false,
      glideslopeCaptured: false,
      reportedBlowThrough: false,
      stabilityChecked: false,
    };
    expect(stripState(makeTestAircraft({ approach: { ...base } }))).toMatch(/vectors/);
    expect(stripState(makeTestAircraft({ approach: { ...base, localiserCaptured: true } }))).toMatch(
      /LOC/,
    );
    expect(
      stripState(
        makeTestAircraft({
          approach: { ...base, localiserCaptured: true, glideslopeCaptured: true },
        }),
      ),
    ).toMatch(/G\/S/);
  });

  it('names the procedure and the next fix on a route', () => {
    const ac = makeTestAircraft({ procedure: 'GUDUR1A' });
    ac.clearance.lateralMode = 'direct';
    ac.clearance.directFix = 'TUMSA';
    expect(stripState(ac)).toBe('GUDUR1A · TUMSA');
  });

  it('falls back to the assigned heading', () => {
    const ac = makeTestAircraft();
    ac.clearance.headingDeg = 75;
    expect(stripState(ac)).toBe('heading 075');
  });
});
