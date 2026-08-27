import { describe, expect, it } from 'vitest';
import { Violation } from './safety.js';
import { ScoreInput, computeScore, formatDuration } from './score.js';

function violation(kind: Violation['kind']): Violation {
  return {
    id: `${kind}-1`,
    kind,
    startedAtSec: 0,
    endedAtSec: 30,
    callsigns: ['AAA1', 'BBB2'],
    requiredLateralNm: 3,
    requiredVerticalFt: 1000,
    actualLateralNm: 1.4,
    actualVerticalFt: 300,
    worstAtSec: 10,
    detail: 'test',
  };
}

const EMPTY: ScoreInput = {
  elapsedSec: 0,
  arrivals: 0,
  departures: 0,
  goArounds: 0,
  fuelBurntKg: 0,
  arrivalDelaysSec: [],
  violations: [],
  onFrequency: 0,
};

describe('the score', () => {
  it('is all zeros before anything happens', () => {
    const score = computeScore(EMPTY);
    expect(score.movements).toBe(0);
    expect(score.movementsPerHour).toBe(0);
    expect(score.averageDelaySec).toBe(0);
    expect(score.totalViolations).toBe(0);
  });

  it('counts movements and works out the rate', () => {
    const score = computeScore({ ...EMPTY, elapsedSec: 1800, arrivals: 9, departures: 6 });
    expect(score.movements).toBe(15);
    expect(score.movementsPerHour).toBeCloseTo(30, 6);
  });

  it('averages the delays and reports the worst', () => {
    const score = computeScore({ ...EMPTY, arrivalDelaysSec: [60, 180, 300] });
    expect(score.averageDelaySec).toBeCloseTo(180, 6);
    expect(score.worstDelaySec).toBe(300);
  });

  it('splits the violations by kind', () => {
    const score = computeScore({
      ...EMPTY,
      violations: [
        violation('stca'),
        violation('stca'),
        violation('wake'),
        violation('msaw'),
        violation('sector-exit'),
      ],
    });
    expect(score.separationLosses).toBe(2);
    expect(score.wakeViolations).toBe(1);
    expect(score.terrainAlerts).toBe(1);
    expect(score.sectorExits).toBe(1);
    expect(score.totalViolations).toBe(5);
  });

  it('passes fuel and traffic through untouched', () => {
    const score = computeScore({ ...EMPTY, fuelBurntKg: 4312.5, onFrequency: 7 });
    expect(score.fuelBurntKg).toBe(4312.5);
    expect(score.onFrequency).toBe(7);
  });
});

describe('formatting a duration', () => {
  it('reads as minutes and seconds', () => {
    expect(formatDuration(0)).toBe('0:00');
    expect(formatDuration(9)).toBe('0:09');
    expect(formatDuration(60)).toBe('1:00');
    expect(formatDuration(185)).toBe('3:05');
    expect(formatDuration(3599)).toBe('59:59');
  });

  it('never shows a negative time', () => {
    expect(formatDuration(-30)).toBe('0:00');
  });
});
