import { describe, expect, it } from 'vitest';
import wakeData from '../data/wake.json';
import { RawWakeMatrix, WakeMatrix } from './wake.js';

const MATRIX = new WakeMatrix(wakeData as unknown as RawWakeMatrix);

describe('the published matrix', () => {
  it('matches the figures in the brief', () => {
    expect(MATRIX.minimumNm('H', 'H')).toBe(4);
    expect(MATRIX.minimumNm('H', 'M')).toBe(5);
    expect(MATRIX.minimumNm('H', 'L')).toBe(6);
  });

  it('applies the super category', () => {
    expect(MATRIX.minimumNm('J', 'H')).toBe(6);
    expect(MATRIX.minimumNm('J', 'M')).toBe(7);
    expect(MATRIX.minimumNm('J', 'L')).toBe(8);
  });

  it('gives medium behind medium the plain radar minimum', () => {
    expect(MATRIX.minimumNm('M', 'M')).toBe(MATRIX.radarMinimumNm);
    expect(MATRIX.isWakeCritical('M', 'M')).toBe(false);
  });

  it('still protects a light behind a medium', () => {
    expect(MATRIX.minimumNm('M', 'L')).toBe(5);
    expect(MATRIX.isWakeCritical('M', 'L')).toBe(true);
  });

  it('is not symmetric — order matters', () => {
    expect(MATRIX.minimumNm('H', 'L')).toBe(6);
    expect(MATRIX.minimumNm('L', 'H')).toBe(3);
  });

  it('never returns less than the radar minimum', () => {
    for (const leader of ['L', 'M', 'H', 'J'] as const) {
      for (const follower of ['L', 'M', 'H', 'J'] as const) {
        expect(MATRIX.minimumNm(leader, follower)).toBeGreaterThanOrEqual(MATRIX.radarMinimumNm);
      }
    }
  });

  it('names its categories', () => {
    expect(MATRIX.categoryName('H')).toBe('Heavy');
    expect(MATRIX.categoryName('J')).toBe('Super');
  });
});

describe('validation', () => {
  it('rejects a matrix with a hole in it', () => {
    const broken = {
      ...(wakeData as unknown as RawWakeMatrix),
      minimaNm: { H: { H: 4 } },
    };
    expect(() => new WakeMatrix(broken)).toThrow(/no minimum for/);
  });

  it('rejects a figure below the radar minimum', () => {
    const raw = wakeData as unknown as RawWakeMatrix;
    const broken: RawWakeMatrix = {
      ...raw,
      minimaNm: { ...raw.minimaNm, H: { J: 3, H: 2, M: 5, L: 6 } },
    };
    expect(() => new WakeMatrix(broken)).toThrow(/below the radar minimum/);
  });
});
