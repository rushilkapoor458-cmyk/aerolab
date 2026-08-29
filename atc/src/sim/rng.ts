/**
 * Deterministic pseudo-random numbers.
 *
 * Every stochastic choice in the simulation draws from one of these, seeded
 * from the scenario seed, so a given seed always reproduces the same session.
 * mulberry32: small, fast, and good enough for traffic generation.
 */
export class Rng {
  private state: number;

  constructor(seed: number) {
    // Mixing the seed keeps small integer seeds from producing similar streams.
    this.state = (seed ^ 0x9e3779b9) >>> 0;
  }

  /** Uniform in [0, 1). */
  next(): number {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  /** Uniform in [min, max). */
  range(min: number, max: number): number {
    return min + this.next() * (max - min);
  }

  /** Uniform integer in [min, max], inclusive. */
  int(min: number, max: number): number {
    return Math.floor(this.range(min, max + 1));
  }

  /** Uniformly pick one element. Throws on an empty array. */
  pick<T>(items: readonly T[]): T {
    if (items.length === 0) throw new Error('Rng.pick called with no items');
    const item = items[this.int(0, items.length - 1)];
    if (item === undefined) throw new Error('Rng.pick produced an out of range index');
    return item;
  }

  /** Seed a fresh independent stream, so subsystems do not disturb each other. */
  fork(): Rng {
    return new Rng(Math.floor(this.next() * 0xffffffff));
  }
}
