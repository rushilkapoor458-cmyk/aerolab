import { describe, expect, it } from 'vitest';
import airspaceData from '../data/airspace.json';
import wakeData from '../data/wake.json';
import { Airspace, RawAirspace } from './airspace.js';
import { movePoint } from './geo.js';
import { SafetyNet } from './safety.js';
import { makeTestAircraft } from './testAircraft.js';
import { Aircraft } from './types.js';
import { RawWakeMatrix, WakeMatrix } from './wake.js';

const AIRSPACE = new Airspace(airspaceData as unknown as RawAirspace);
const WAKE = new WakeMatrix(wakeData as unknown as RawWakeMatrix);
const RUNWAY_29 = AIRSPACE.runway('29');
if (RUNWAY_29 === undefined) throw new Error('runway 29 missing');
const RUNWAY = RUNWAY_29;

function net(): SafetyNet {
  return new SafetyNet(AIRSPACE, WAKE);
}

/** An aircraft on final for 29, `distanceNm` from the threshold. */
function onFinal(callsign: string, distanceNm: number, type: string, captured = true): Aircraft {
  const reciprocal = (RUNWAY.trueHeadingDeg + 180) % 360;
  return makeTestAircraft(
    {
      callsign,
      position: movePoint(RUNWAY.threshold, reciprocal, distanceNm),
      altitudeFt: 827 + distanceNm * 318.4,
      trueTrackDeg: RUNWAY.trueHeadingDeg,
      headingDeg: RUNWAY.trueHeadingDeg,
      groundspeedKt: 150,
      approach: {
        runway: '29',
        ident: 'ILS29',
        localiserCaptured: captured,
        glideslopeCaptured: captured,
        reportedBlowThrough: false,
        stabilityChecked: false,
      },
    },
    type,
  );
}

describe('short term conflict alert', () => {
  it('says nothing when the picture is clean', () => {
    const safety = net();
    safety.update(
      [
        makeTestAircraft({ position: { x: 0, y: 20 }, altitudeFt: 7000, trueTrackDeg: 0 }),
        makeTestAircraft({ position: { x: 0, y: -20 }, altitudeFt: 7000, trueTrackDeg: 180 }),
      ],
      0,
    );
    expect(safety.alerts.filter((a) => a.kind === 'stca')).toHaveLength(0);
  });

  it('raises an amber caution for a predicted loss', () => {
    const safety = net();
    safety.update(
      [
        makeTestAircraft({
          callsign: 'AAA1', position: { x: -5, y: 10 }, altitudeFt: 7000,
          trueTrackDeg: 90, groundspeedKt: 300,
        }),
        makeTestAircraft({
          callsign: 'BBB2', position: { x: 5, y: 10 }, altitudeFt: 7000,
          trueTrackDeg: 270, groundspeedKt: 300,
        }),
      ],
      0,
    );
    const alert = safety.alerts.find((a) => a.kind === 'stca');
    expect(alert?.severity).toBe('caution');
    expect(alert?.message).toMatch(/predicted loss in \d+ s/);
    expect(alert?.callsigns).toEqual(['AAA1', 'BBB2']);
    expect(safety.violations).toHaveLength(0);
  });

  it('raises a red warning and logs the violation on an actual loss', () => {
    const safety = net();
    const a = makeTestAircraft({ callsign: 'AAA1', position: { x: 0, y: 10 }, altitudeFt: 7000 });
    const b = makeTestAircraft({ callsign: 'BBB2', position: { x: 1.5, y: 10 }, altitudeFt: 7300 });
    safety.update([a, b], 3600);

    const alert = safety.alerts.find((x) => x.kind === 'stca');
    expect(alert?.severity).toBe('warning');
    expect(alert?.message).toMatch(/separation lost/);

    expect(safety.violations).toHaveLength(1);
    const violation = safety.violations[0];
    expect(violation?.kind).toBe('stca');
    expect(violation?.startedAtSec).toBe(3600);
    expect(violation?.callsigns).toEqual(['AAA1', 'BBB2']);
    expect(violation?.requiredLateralNm).toBe(3);
    expect(violation?.requiredVerticalFt).toBe(1000);
    expect(violation?.actualLateralNm).toBeCloseTo(1.5, 6);
    expect(violation?.actualVerticalFt).toBeCloseTo(300, 6);
  });

  it('keeps the worst values seen, not the first', () => {
    const safety = net();
    const a = makeTestAircraft({ callsign: 'AAA1', position: { x: 0, y: 10 }, altitudeFt: 7000 });
    const b = makeTestAircraft({ callsign: 'BBB2', position: { x: 2.5, y: 10 }, altitudeFt: 7000 });
    safety.update([a, b], 100);
    b.position = { x: 0.8, y: 10 };
    safety.update([a, b], 130);
    b.position = { x: 2.0, y: 10 };
    safety.update([a, b], 160);

    expect(safety.violations).toHaveLength(1);
    expect(safety.violations[0]?.actualLateralNm).toBeCloseTo(0.8, 6);
    expect(safety.violations[0]?.worstAtSec).toBe(130);
  });

  it('logs one violation per episode, and closes it when it resolves', () => {
    const safety = net();
    const a = makeTestAircraft({ callsign: 'AAA1', position: { x: 0, y: 10 }, altitudeFt: 7000 });
    const b = makeTestAircraft({ callsign: 'BBB2', position: { x: 2, y: 10 }, altitudeFt: 7000 });
    safety.update([a, b], 100);
    safety.update([a, b], 101);
    expect(safety.violations).toHaveLength(1);

    b.altitudeFt = 9000; // Resolved vertically.
    safety.update([a, b], 200);
    expect(safety.violations).toHaveLength(1);
    expect(safety.violations[0]?.endedAtSec).toBe(200);

    b.altitudeFt = 7000; // And a second, separate episode.
    safety.update([a, b], 300);
    expect(safety.violations).toHaveLength(2);
  });

  it('ignores an aircraft that has been handed off', () => {
    const safety = net();
    const a = makeTestAircraft({ position: { x: 0, y: 10 }, altitudeFt: 7000 });
    const b = makeTestAircraft({ position: { x: 1, y: 10 }, altitudeFt: 7000, handedOff: true });
    safety.update([a, b], 0);
    expect(safety.alerts.filter((x) => x.kind === 'stca')).toHaveLength(0);
  });

  it('uses five miles when the pair is outside the terminal area', () => {
    const safety = net();
    const a = makeTestAircraft({ callsign: 'AAA1', position: { x: 0, y: 45 }, altitudeFt: 9000 });
    const b = makeTestAircraft({ callsign: 'BBB2', position: { x: 4, y: 45 }, altitudeFt: 9000 });
    safety.update([a, b], 0);
    expect(safety.alerts.find((x) => x.kind === 'stca')?.severity).toBe('warning');
    expect(safety.violations[0]?.requiredLateralNm).toBe(5);
  });
});

describe('wake turbulence on final', () => {
  it('lets a medium follow a medium at three and a half miles', () => {
    const safety = net();
    safety.update([onFinal('LEAD', 5, 'A320'), onFinal('TRAIL', 8.5, 'B738')], 0);
    expect(safety.alerts.filter((a) => a.kind === 'wake')).toHaveLength(0);
  });

  it('will not let a medium follow a heavy at four miles', () => {
    const safety = net();
    safety.update([onFinal('LEAD', 5, 'B77W'), onFinal('TRAIL', 9, 'A320')], 0);
    const alert = safety.alerts.find((a) => a.kind === 'wake');
    expect(alert?.severity).toBe('warning');
    expect(alert?.message).toMatch(/5 NM required/);
    expect(safety.violations[0]?.requiredLateralNm).toBe(5);
    expect(safety.violations[0]?.actualLateralNm).toBeCloseTo(4, 6);
  });

  it('needs six miles for a light behind a heavy', () => {
    const safety = net();
    safety.update([onFinal('LEAD', 4, 'B77W'), onFinal('TRAIL', 9.5, 'C172')], 0);
    expect(safety.alerts.find((a) => a.kind === 'wake')?.message).toMatch(/6 NM required/);
  });

  it('ignores aircraft that are not on an approach at all', () => {
    const safety = net();
    const lead = onFinal('LEAD', 5, 'B77W');
    const trail = onFinal('TRAIL', 8, 'A320');
    trail.approach = null;
    safety.update([lead, trail], 0);
    expect(safety.alerts.filter((a) => a.kind === 'wake')).toHaveLength(0);
  });

  it('ignores traffic beyond the range where wake is applied', () => {
    const safety = net();
    safety.update([onFinal('LEAD', 20, 'B77W'), onFinal('TRAIL', 23, 'A320')], 0);
    expect(safety.alerts.filter((a) => a.kind === 'wake')).toHaveLength(0);
  });
});

describe('minimum safe altitude warning', () => {
  it('fires when an aircraft is below the grid', () => {
    const safety = net();
    const low = makeTestAircraft({ callsign: 'LOW1', position: { x: -45, y: -30 }, altitudeFt: 2000 });
    safety.update([low], 500);
    const alert = safety.alerts.find((a) => a.kind === 'msaw');
    expect(alert?.severity).toBe('warning');
    expect(alert?.message).toMatch(/terrain/);
    expect(safety.violations[0]?.kind).toBe('msaw');
    expect(safety.violations[0]?.actualVerticalFt).toBe(2000);
    expect(safety.violations[0]?.requiredVerticalFt).toBeGreaterThan(2000);
  });

  it('cautions an aircraft descending towards it', () => {
    const safety = net();
    const sinking = makeTestAircraft({
      position: { x: -45, y: -30 }, altitudeFt: 4600, verticalSpeedFpm: -2000,
    });
    sinking.clearance.altitudeFt = 2000;
    safety.update([sinking], 0);
    expect(safety.alerts.find((a) => a.kind === 'msaw')?.severity).toBe('caution');
    expect(safety.violations).toHaveLength(0);
  });

  it('is suppressed once the aircraft is established on an approach', () => {
    const safety = net();
    safety.update([onFinal('TEST1', 4, 'A320')], 0);
    expect(safety.alerts.filter((a) => a.kind === 'msaw')).toHaveLength(0);
  });

  it('is not suppressed merely by being cleared for one', () => {
    const safety = net();
    const low = onFinal('TEST2', 4, 'A320', false);
    low.altitudeFt = 1200;
    safety.update([low], 0);
    expect(safety.alerts.filter((a) => a.kind === 'msaw')).toHaveLength(1);
  });
});

describe('sector exits', () => {
  it('warns about an aircraft outside the sector that is still on frequency', () => {
    const safety = net();
    const gone = makeTestAircraft({ callsign: 'GONE1', position: { x: 0, y: 90 }, altitudeFt: 9000 });
    safety.update([gone], 400);
    const alert = safety.alerts.find((a) => a.kind === 'sector-exit');
    expect(alert?.severity).toBe('warning');
    expect(safety.violations[0]?.kind).toBe('sector-exit');
    expect(safety.violations[0]?.detail).toMatch(/left the sector unhandled/);
  });

  it('says nothing about one that has been handed off', () => {
    const safety = net();
    const gone = makeTestAircraft({ position: { x: 0, y: 90 }, handedOff: true });
    safety.update([gone], 0);
    expect(safety.alerts.filter((a) => a.kind === 'sector-exit')).toHaveLength(0);
  });

  it('cautions before it happens', () => {
    const safety = net();
    // Just inside the boundary, tracking straight out at speed.
    const leaving = makeTestAircraft({
      position: { x: 0, y: 60 }, trueTrackDeg: 0, groundspeedKt: 450, altitudeFt: 9000,
    });
    safety.update([leaving], 0);
    expect(safety.alerts.find((a) => a.kind === 'sector-exit')?.severity).toBe('caution');
    expect(safety.violations).toHaveLength(0);
  });
});

describe('alert bookkeeping', () => {
  it('keeps the timestamp while an alert persists', () => {
    const safety = net();
    const a = makeTestAircraft({ position: { x: 0, y: 10 }, altitudeFt: 7000 });
    const b = makeTestAircraft({ position: { x: 1, y: 10 }, altitudeFt: 7000 });
    safety.update([a, b], 100);
    const first = safety.alerts[0]?.sinceSec;
    safety.update([a, b], 160);
    expect(safety.alerts[0]?.sinceSec).toBe(first);
  });

  it('sorts warnings above cautions', () => {
    const safety = net();
    const warningPair = [
      makeTestAircraft({ callsign: 'WARN1', position: { x: 0, y: 10 }, altitudeFt: 7000 }),
      makeTestAircraft({ callsign: 'WARN2', position: { x: 1, y: 10 }, altitudeFt: 7000 }),
    ];
    const cautionPair = [
      makeTestAircraft({
        callsign: 'CAUT1', position: { x: -5, y: -20 }, altitudeFt: 5000,
        trueTrackDeg: 90, groundspeedKt: 300,
      }),
      makeTestAircraft({
        callsign: 'CAUT2', position: { x: 5, y: -20 }, altitudeFt: 5000,
        trueTrackDeg: 270, groundspeedKt: 300,
      }),
    ];
    safety.update([...cautionPair, ...warningPair], 0);
    expect(safety.alerts[0]?.severity).toBe('warning');
  });

  it('reports the alerts and worst severity for one aircraft', () => {
    const safety = net();
    const a = makeTestAircraft({ callsign: 'AAA1', position: { x: 0, y: 10 }, altitudeFt: 7000 });
    const b = makeTestAircraft({ callsign: 'BBB2', position: { x: 1, y: 10 }, altitudeFt: 7000 });
    safety.update([a, b], 0);
    expect(safety.alertsFor(a.id)).toHaveLength(1);
    expect(safety.severityFor(a.id)).toBe('warning');
    expect(safety.severityFor('nobody')).toBeNull();
  });
});
