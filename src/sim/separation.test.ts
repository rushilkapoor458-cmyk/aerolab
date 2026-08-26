import { describe, expect, it } from 'vitest';
import {
  OUTER_LATERAL_NM,
  TMA_LATERAL_NM,
  VERTICAL_SEPARATION_FT,
  assessConflict,
  currentSeparation,
  projectedAltitudeFt,
  projectedPosition,
  rangeFromFieldNm,
  standardFor,
} from './separation.js';
import { makeTestAircraft } from './testAircraft.js';

describe('which standard applies', () => {
  it('is three miles inside the terminal area', () => {
    const a = makeTestAircraft({ position: { x: 10, y: 0 } });
    const b = makeTestAircraft({ position: { x: 14, y: 0 } });
    expect(standardFor(a, b)).toEqual({
      lateralNm: TMA_LATERAL_NM,
      verticalFt: VERTICAL_SEPARATION_FT,
    });
  });

  it('is five miles as soon as either aircraft is outside forty', () => {
    const inside = makeTestAircraft({ position: { x: 10, y: 0 } });
    const outside = makeTestAircraft({ position: { x: 45, y: 0 } });
    expect(standardFor(inside, outside).lateralNm).toBe(OUTER_LATERAL_NM);
    expect(standardFor(outside, inside).lateralNm).toBe(OUTER_LATERAL_NM);
  });

  it('measures range from the aerodrome', () => {
    expect(rangeFromFieldNm(makeTestAircraft({ position: { x: 3, y: 4 } }))).toBeCloseTo(5, 9);
  });
});

describe('projection', () => {
  it('carries the aircraft along its ground track', () => {
    const ac = makeTestAircraft({ trueTrackDeg: 90, groundspeedKt: 360 });
    const ahead = projectedPosition(ac, 60);
    expect(ahead.x).toBeCloseTo(6, 6);
    expect(ahead.y).toBeCloseTo(0, 6);
  });

  it('levels off at the cleared altitude instead of descending for ever', () => {
    const ac = makeTestAircraft({ altitudeFt: 8000, verticalSpeedFpm: -2000 });
    ac.clearance.altitudeFt = 6000;
    expect(projectedAltitudeFt(ac, 30)).toBeCloseTo(7000, 6);
    expect(projectedAltitudeFt(ac, 120)).toBe(6000);
  });

  it('does the same in the climb', () => {
    const ac = makeTestAircraft({ altitudeFt: 4000, verticalSpeedFpm: 2000 });
    ac.clearance.altitudeFt = 5000;
    expect(projectedAltitudeFt(ac, 120)).toBe(5000);
  });

  it('holds level when it is not going anywhere', () => {
    const ac = makeTestAircraft({ altitudeFt: 7000, verticalSpeedFpm: 0 });
    expect(projectedAltitudeFt(ac, 300)).toBe(7000);
  });
});

describe('assessing a pair', () => {
  const standard = { lateralNm: TMA_LATERAL_NM, verticalFt: VERTICAL_SEPARATION_FT };

  it('says nothing about traffic that is nowhere near', () => {
    const a = makeTestAircraft({ position: { x: 0, y: 0 }, trueTrackDeg: 0, groundspeedKt: 250 });
    const b = makeTestAircraft({ position: { x: 30, y: 0 }, trueTrackDeg: 180, groundspeedKt: 250 });
    expect(assessConflict(a, b, standard).severity).toBe('none');
  });

  it('calls an actual loss when both minima are broken now', () => {
    const a = makeTestAircraft({ position: { x: 0, y: 0 }, altitudeFt: 7000 });
    const b = makeTestAircraft({ position: { x: 2, y: 0 }, altitudeFt: 7400 });
    const result = assessConflict(a, b, standard);
    expect(result.severity).toBe('loss');
    expect(result.timeToLossSec).toBe(0);
    expect(result.closestDistanceNm).toBeCloseTo(2, 6);
    expect(result.closestVerticalFt).toBeCloseTo(400, 6);
  });

  it('is happy with two miles apart when they are a thousand feet apart', () => {
    const a = makeTestAircraft({ position: { x: 0, y: 0 }, altitudeFt: 7000 });
    const b = makeTestAircraft({ position: { x: 2, y: 0 }, altitudeFt: 8000 });
    expect(assessConflict(a, b, standard).severity).toBe('none');
  });

  it('predicts a loss for converging traffic at the same level', () => {
    // Head on, ten miles apart, 300 kt each: about a minute to run.
    const a = makeTestAircraft({
      position: { x: -5, y: 0 }, trueTrackDeg: 90, groundspeedKt: 300, altitudeFt: 7000,
    });
    const b = makeTestAircraft({
      position: { x: 5, y: 0 }, trueTrackDeg: 270, groundspeedKt: 300, altitudeFt: 7000,
    });
    const result = assessConflict(a, b, standard);
    expect(result.severity).toBe('predicted');
    expect(result.timeToLossSec).toBeGreaterThan(0);
    expect(result.timeToLossSec).toBeLessThan(120);
    expect(result.closestDistanceNm).toBeLessThan(1);
  });

  it('leaves converging traffic alone when it is vertically separated', () => {
    const a = makeTestAircraft({
      position: { x: -5, y: 0 }, trueTrackDeg: 90, groundspeedKt: 300, altitudeFt: 7000,
    });
    const b = makeTestAircraft({
      position: { x: 5, y: 0 }, trueTrackDeg: 270, groundspeedKt: 300, altitudeFt: 9000,
    });
    expect(assessConflict(a, b, standard).severity).toBe('none');
  });

  it('catches one descending through another', () => {
    const a = makeTestAircraft({
      position: { x: 0, y: 0 }, trueTrackDeg: 90, groundspeedKt: 250, altitudeFt: 9000,
      verticalSpeedFpm: -2000,
    });
    a.clearance.altitudeFt = 5000;
    const b = makeTestAircraft({
      position: { x: 1, y: 0 }, trueTrackDeg: 90, groundspeedKt: 250, altitudeFt: 7000,
    });
    b.clearance.altitudeFt = 7000;
    const result = assessConflict(a, b, standard);
    expect(result.severity).toBe('predicted');
  });

  it('does not raise a conflict that the level-off prevents', () => {
    const a = makeTestAircraft({
      position: { x: 0, y: 0 }, trueTrackDeg: 90, groundspeedKt: 250, altitudeFt: 9000,
      verticalSpeedFpm: -2000,
    });
    a.clearance.altitudeFt = 8100; // Stops well above the other aircraft.
    const b = makeTestAircraft({
      position: { x: 1, y: 0 }, trueTrackDeg: 90, groundspeedKt: 250, altitudeFt: 7000,
    });
    b.clearance.altitudeFt = 7000;
    expect(assessConflict(a, b, standard).severity).toBe('none');
  });

  it('reports the closest point it found', () => {
    const a = makeTestAircraft({
      position: { x: -10, y: 0 }, trueTrackDeg: 90, groundspeedKt: 600, altitudeFt: 7000,
    });
    const b = makeTestAircraft({
      position: { x: 0, y: 2 }, trueTrackDeg: 90, groundspeedKt: 600, altitudeFt: 7000,
    });
    const result = assessConflict(a, b, standard);
    expect(result.closestDistanceNm).toBeLessThan(11);
    expect(result.closestAtSec).toBeGreaterThanOrEqual(0);
  });
});

describe('present separation', () => {
  it('is a plain measurement with no prediction in it', () => {
    const a = makeTestAircraft({ position: { x: 0, y: 0 }, altitudeFt: 7000 });
    const b = makeTestAircraft({ position: { x: 3, y: 4 }, altitudeFt: 8200 });
    expect(currentSeparation(a, b)).toEqual({ lateralNm: 5, verticalFt: 1200 });
  });
});
