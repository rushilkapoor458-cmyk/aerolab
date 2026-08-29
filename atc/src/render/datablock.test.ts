import { describe, expect, it } from 'vitest';
import { DataBlockRequest, layoutDataBlocks, leaderEndPoint } from './datablock.js';

/** A stand-in for canvas text measurement: seven pixels per character. */
const measure = (text: string): number => text.length * 7;

function request(id: string, x: number, y: number, selected = false): DataBlockRequest {
  return {
    id,
    anchor: { x, y },
    lines: [`${id} M`, '110↓090', '287 250 TUMSA'],
    selected,
    severity: 'normal',
  };
}

function overlapping(
  a: { x: number; y: number; w: number; h: number },
  b: { x: number; y: number; w: number; h: number },
): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

describe('data block layout', () => {
  it('places a lone block up and to the right of its target', () => {
    const placed = layoutDataBlocks([request('AIC101', 200, 200)], measure);
    expect(placed).toHaveLength(1);
    const box = placed[0]?.box;
    expect(box).toBeDefined();
    if (box === undefined) return;
    expect(box.x).toBeGreaterThan(200);
    expect(box.y + box.h).toBeLessThan(200 + 1);
  });

  it('offsets blocks so that two aircraft in trail do not overwrite each other', () => {
    const placed = layoutDataBlocks(
      [request('AIC101', 300, 300), request('IGO2145', 316, 288)],
      measure,
    );
    const first = placed[0]?.box;
    const second = placed[1]?.box;
    expect(first).toBeDefined();
    expect(second).toBeDefined();
    if (first === undefined || second === undefined) return;
    expect(overlapping(first, second)).toBe(false);
  });

  it('keeps a cluster of four aircraft clear of each other', () => {
    // Four targets within a mile of each other at a typical scope zoom.
    const requests = [
      request('AIC101', 400, 400),
      request('IGO2145', 430, 428),
      request('VTI872', 372, 430),
      request('SEJ301', 404, 462),
    ];
    const placed = layoutDataBlocks(requests, measure);
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        const a = placed[i]?.box;
        const b = placed[j]?.box;
        if (a === undefined || b === undefined) continue;
        expect(overlapping(a, b)).toBe(false);
      }
    }
  });

  it('keeps a line of eight aircraft in trail clear of each other', () => {
    const requests = Array.from({ length: 8 }, (_, i) => request(`AC${i}`, 80 + i * 130, 300));
    const placed = layoutDataBlocks(requests, measure);
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        const a = placed[i]?.box;
        const b = placed[j]?.box;
        if (a === undefined || b === undefined) continue;
        expect(overlapping(a, b)).toBe(false);
      }
    }
  });

  it('gives the selected aircraft its preferred position whatever the order', () => {
    const forwards = layoutDataBlocks(
      [request('AAA111', 500, 500), request('ZZZ999', 512, 494, true)],
      measure,
    );
    const chosen = forwards.find((p) => p.id === 'ZZZ999')?.box;
    expect(chosen).toBeDefined();
    if (chosen === undefined) return;
    expect(chosen.x).toBeGreaterThan(512);
  });

  it('returns one placement per request and never loses a block', () => {
    const requests = Array.from({ length: 20 }, (_, i) => request(`AC${i}`, 100 + i * 3, 100 + i * 2));
    const placed = layoutDataBlocks(requests, measure);
    expect(placed).toHaveLength(20);
    expect(new Set(placed.map((p) => p.id)).size).toBe(20);
  });
});

describe('viewport clamping', () => {
  const viewport = { width: 1000, height: 800 };

  it('keeps a block by the top edge fully on the scope', () => {
    const placed = layoutDataBlocks([request('VTI872', 500, 6)], measure, viewport);
    const box = placed[0]?.box;
    expect(box).toBeDefined();
    if (box === undefined) return;
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.y + box.h).toBeLessThanOrEqual(viewport.height);
  });

  it('keeps a block by the right edge fully on the scope', () => {
    const placed = layoutDataBlocks([request('VTI872', 992, 400)], measure, viewport);
    const box = placed[0]?.box;
    expect(box).toBeDefined();
    if (box === undefined) return;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.w).toBeLessThanOrEqual(viewport.width);
  });

  it('leaves a block in the middle of the scope where it was', () => {
    const withViewport = layoutDataBlocks([request('AIC101', 500, 400)], measure, viewport);
    const without = layoutDataBlocks([request('AIC101', 500, 400)], measure);
    expect(withViewport[0]?.box).toEqual(without[0]?.box);
  });
});

describe('leader lines', () => {
  const box = { x: 100, y: 100, w: 100, h: 40 };

  it('stops on the near edge of the block', () => {
    const end = leaderEndPoint({ x: 60, y: 120 }, box);
    expect(end).not.toBeNull();
    expect(end?.x).toBeCloseTo(100, 6);
    expect(end?.y).toBeCloseTo(120, 6);
  });

  it('stops on the top edge when the target is below', () => {
    const end = leaderEndPoint({ x: 150, y: 200 }, box);
    expect(end).not.toBeNull();
    expect(end?.y).toBeCloseTo(140, 6);
  });

  it('never lands inside the block', () => {
    for (let angle = 0; angle < 360; angle += 7) {
      const r = 120;
      const anchor = {
        x: 150 + Math.cos((angle * Math.PI) / 180) * r,
        y: 120 + Math.sin((angle * Math.PI) / 180) * r,
      };
      const end = leaderEndPoint(anchor, box);
      if (end === null) continue;
      const insideX = end.x > box.x + 1e-6 && end.x < box.x + box.w - 1e-6;
      const insideY = end.y > box.y + 1e-6 && end.y < box.y + box.h - 1e-6;
      expect(insideX && insideY).toBe(false);
    }
  });

  it('draws nothing when the target sits inside the block', () => {
    expect(leaderEndPoint({ x: 150, y: 120 }, box)).toBeNull();
  });
});
