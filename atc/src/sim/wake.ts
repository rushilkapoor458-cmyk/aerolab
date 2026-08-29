/**
 * Wake turbulence separation on final approach.
 *
 * The matrix lives in `src/data/wake.json` so it can be edited without
 * touching code. Anything the matrix does not cover falls back to the radar
 * minimum, which is what happens in life.
 */

import { WakeCategory } from './types.js';

export interface WakeCategoryInfo {
  readonly code: WakeCategory;
  readonly name: string;
  readonly maximumMassKg: number | null;
}

export interface RawWakeMatrix {
  schemaVersion: number;
  radarMinimumNm: number;
  categories: WakeCategoryInfo[];
  /** Leader category to follower category to minimum separation, NM. */
  minimaNm: Record<string, Record<string, number>>;
}

const ORDER: readonly WakeCategory[] = ['L', 'M', 'H', 'J'];

export class WakeMatrix {
  readonly radarMinimumNm: number;
  readonly categories: readonly WakeCategoryInfo[];
  private readonly minima: ReadonlyMap<string, number>;

  constructor(raw: RawWakeMatrix) {
    this.radarMinimumNm = raw.radarMinimumNm;
    this.categories = [...raw.categories];

    const minima = new Map<string, number>();
    for (const [leader, followers] of Object.entries(raw.minimaNm)) {
      for (const [follower, nm] of Object.entries(followers)) {
        minima.set(key(leader, follower), nm);
      }
    }
    this.minima = minima;
    this.validate();
  }

  private validate(): void {
    const problems: string[] = [];
    for (const leader of ORDER) {
      for (const follower of ORDER) {
        const value = this.minima.get(key(leader, follower));
        if (value === undefined) {
          problems.push(`wake.json has no minimum for ${follower} behind ${leader}`);
        } else if (value < this.radarMinimumNm) {
          problems.push(
            `${follower} behind ${leader} is ${value} NM, below the radar minimum of ${this.radarMinimumNm} NM`,
          );
        }
      }
    }
    if (problems.length > 0) {
      throw new Error(`wake.json is inconsistent:\n  - ${problems.join('\n  - ')}`);
    }
  }

  /**
   * Minimum in-trail separation for `follower` behind `leader`, in NM.
   * Never less than the radar minimum.
   */
  minimumNm(leader: WakeCategory, follower: WakeCategory): number {
    return Math.max(this.radarMinimumNm, this.minima.get(key(leader, follower)) ?? this.radarMinimumNm);
  }

  /** True when the pair needs more than the plain radar minimum. */
  isWakeCritical(leader: WakeCategory, follower: WakeCategory): boolean {
    return this.minimumNm(leader, follower) > this.radarMinimumNm;
  }

  categoryName(code: WakeCategory): string {
    return this.categories.find((c) => c.code === code)?.name ?? code;
  }
}

function key(leader: string, follower: string): string {
  return `${leader.toUpperCase()}>${follower.toUpperCase()}`;
}
