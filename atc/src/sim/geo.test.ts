import { describe, expect, it } from 'vitest';
import {
  Projection,
  alongTrackNm,
  angleDiff,
  bearingDeg,
  crossTrackNm,
  distanceNm,
  formatBearing,
  movePoint,
  normalizeDeg,
  pointInPolygon,
  trueToMagnetic,
} from './geo.js';

const VIDP = { lat: 28.5665, lon: 77.1031 };

describe('normalizeDeg and angleDiff', () => {
  it('wraps into [0, 360)', () => {
    expect(normalizeDeg(0)).toBe(0);
    expect(normalizeDeg(360)).toBe(0);
    expect(normalizeDeg(-10)).toBe(350);
    expect(normalizeDeg(730)).toBe(10);
  });

  it('gives the short way round, signed clockwise', () => {
    expect(angleDiff(350, 10)).toBe(20);
    expect(angleDiff(10, 350)).toBe(-20);
    expect(angleDiff(90, 270)).toBe(180);
    expect(angleDiff(270, 90)).toBe(180);
    expect(angleDiff(0, 0)).toBe(0);
  });
});

describe('projection', () => {
  const projection = new Projection(VIDP);

  it('puts the origin at zero', () => {
    const p = projection.toLocal(VIDP);
    expect(p.x).toBeCloseTo(0, 10);
    expect(p.y).toBeCloseTo(0, 10);
  });

  it('round trips a point 40 NM out', () => {
    const start = { x: 24, y: -32 };
    const back = projection.toLocal(projection.toLatLon(start));
    expect(back.x).toBeCloseTo(start.x, 9);
    expect(back.y).toBeCloseTo(start.y, 9);
  });

  it('makes one minute of latitude one nautical mile', () => {
    const north = projection.toLocal({ lat: VIDP.lat + 1 / 60, lon: VIDP.lon });
    expect(north.y).toBeCloseTo(1, 9);
    expect(north.x).toBeCloseTo(0, 9);
  });
});

describe('bearing, distance and movement', () => {
  it('measures the cardinal directions', () => {
    const origin = { x: 0, y: 0 };
    expect(bearingDeg(origin, { x: 0, y: 5 })).toBeCloseTo(0);
    expect(bearingDeg(origin, { x: 5, y: 0 })).toBeCloseTo(90);
    expect(bearingDeg(origin, { x: 0, y: -5 })).toBeCloseTo(180);
    expect(bearingDeg(origin, { x: -5, y: 0 })).toBeCloseTo(270);
  });

  it('moving along a bearing then measuring it returns the same bearing', () => {
    const start = { x: -12, y: 7 };
    const moved = movePoint(start, 237, 18.4);
    expect(distanceNm(start, moved)).toBeCloseTo(18.4, 9);
    expect(bearingDeg(start, moved)).toBeCloseTo(237, 9);
  });
});

describe('cross track and along track', () => {
  const origin = { x: 0, y: 0 };

  it('is positive to the right of the course', () => {
    // Course due north; a point to the east is to the right.
    expect(crossTrackNm({ x: 3, y: 10 }, origin, 0)).toBeCloseTo(3);
    expect(crossTrackNm({ x: -3, y: 10 }, origin, 0)).toBeCloseTo(-3);
  });

  it('is positive ahead along the course', () => {
    expect(alongTrackNm({ x: 3, y: 10 }, origin, 0)).toBeCloseTo(10);
    expect(alongTrackNm({ x: 0, y: -4 }, origin, 0)).toBeCloseTo(-4);
  });
});

describe('polygon containment', () => {
  const square = [
    { x: -10, y: -10 },
    { x: 10, y: -10 },
    { x: 10, y: 10 },
    { x: -10, y: 10 },
  ];

  it('separates inside from outside', () => {
    expect(pointInPolygon({ x: 0, y: 0 }, square)).toBe(true);
    expect(pointInPolygon({ x: 9.9, y: -9.9 }, square)).toBe(true);
    expect(pointInPolygon({ x: 10.1, y: 0 }, square)).toBe(false);
    expect(pointInPolygon({ x: 0, y: 40 }, square)).toBe(false);
  });
});

describe('magnetic conversion and formatting', () => {
  it('subtracts easterly variation to get magnetic', () => {
    expect(trueToMagnetic(292.6, 0.6)).toBeCloseTo(292);
    expect(trueToMagnetic(0.4, 0.6)).toBeCloseTo(359.8);
  });

  it('formats three digits and calls north 360', () => {
    expect(formatBearing(7)).toBe('007');
    expect(formatBearing(0)).toBe('360');
    expect(formatBearing(360)).toBe('360');
    expect(formatBearing(271.4)).toBe('271');
  });
});
