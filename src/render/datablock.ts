/**
 * Data block text and placement.
 *
 * Blocks are hung off the target on a leader line. When two blocks would
 * overlap, the later one tries the next leader direction round the clock, so
 * a tight stream of traffic stays readable without the controller dragging
 * anything about.
 */

import { Airspace } from '../sim/airspace.js';
import { AlertSeverity } from '../sim/safety.js';
import { Aircraft } from '../sim/types.js';
import { formatFlightLevel } from '../sim/units.js';
import { ScreenPoint } from './camera.js';

export interface Box {
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

/**
 * How the block should be drawn. `caution` is a minimum fuel advisory, `alert`
 * a declared emergency, and `dim` an aircraft already handed to someone else.
 */
export type DataBlockSeverity = 'normal' | 'caution' | 'alert' | 'dim';

export interface DataBlockRequest {
  readonly id: string;
  readonly anchor: ScreenPoint;
  readonly lines: readonly string[];
  readonly selected: boolean;
  readonly severity: DataBlockSeverity;
}

export interface PlacedDataBlock extends DataBlockRequest {
  readonly box: Box;
}

export const LINE_HEIGHT_PX = 12;
export const BLOCK_PADDING_PX = 3;
export const LEADER_LENGTH_PX = 26;

/** Leader directions tried in order, as unit vectors in screen space. */
const LEADER_DIRECTIONS: readonly ScreenPoint[] = [
  { x: 0.707, y: -0.707 }, // up-right, the conventional first choice
  { x: 0.707, y: 0.707 },
  { x: -0.707, y: -0.707 },
  { x: -0.707, y: 0.707 },
  { x: 1, y: 0 },
  { x: -1, y: 0 },
  { x: 0, y: -1 },
  { x: 0, y: 1 },
];

/**
 * The third field of the bottom line: what the aircraft is steering by.
 * A fix name on a route, the hold, the approach, or the assigned heading.
 */
export function navigationField(ac: Aircraft): string {
  if (ac.approach !== null) {
    const stage = ac.approach.glideslopeCaptured
      ? '\u25bc' // On the glidepath.
      : ac.approach.localiserCaptured
        ? '\u2016' // Established on the localiser.
        : '\u2192'; // Cleared, but still on vectors for it.
  return `${stage}ILS${ac.approach.runway}`;
  }
  if (ac.hold !== null) return `HOLD ${ac.hold.fix}`;
  if (ac.clearance.lateralMode === 'direct' && ac.clearance.directFix !== null) {
    return ac.clearance.directFix;
  }
  return `H${Math.round(ac.clearance.headingDeg).toString().padStart(3, '0')}`;
}

/**
 * How this aircraft's block should be coloured. A safety net alert outranks
 * everything else: a controller must see the conflict before anything.
 */
export function dataBlockSeverity(
  ac: Aircraft,
  alert: AlertSeverity | null = null,
): DataBlockSeverity {
  if (alert === 'warning' || ac.fuelState === 'emergency') return 'alert';
  if (alert === 'caution') return 'caution';
  if (ac.handedOff) return 'dim';
  if (ac.fuelState === 'minimum') return 'caution';
  return 'normal';
}

/** The three lines of a full data block. */
export function dataBlockLines(ac: Aircraft, airspace: Airspace): string[] {
  const arrow =
    ac.verticalSpeedFpm > 200 ? '↑' : ac.verticalSpeedFpm < -200 ? '↓' : '→';
  const nextFix = navigationField(ac);
  // A tag after the wake category: the state the controller must not forget.
  const tag =
    ac.fuelState === 'emergency'
      ? ' EMG'
      : ac.handedOff
        ? ' HO'
        : ac.fuelState === 'minimum'
          ? ' MIN'
          : '';
  void airspace;
  return [
    `${ac.callsign} ${ac.wake}${tag}`,
    `${formatFlightLevel(ac.altitudeFt)}${arrow}${formatFlightLevel(ac.clearance.altitudeFt)}`,
    `${Math.round(ac.groundspeedKt).toString().padStart(3, '0')} ${Math.round(ac.clearance.speedKt)} ${nextFix}`,
  ];
}

/**
 * Where a leader line drawn from the target towards a block should stop: the
 * point at which it first meets the block's edge. Returns null when the
 * target is inside the block, where no leader should be drawn at all.
 */
export function leaderEndPoint(anchor: ScreenPoint, box: Box): ScreenPoint | null {
  const centre = { x: box.x + box.w / 2, y: box.y + box.h / 2 };
  const dx = centre.x - anchor.x;
  const dy = centre.y - anchor.y;
  if (dx === 0 && dy === 0) return null;

  // Slab method: the ray enters the box at the largest of the per-axis entries.
  const entry = (min: number, max: number, origin: number, direction: number): [number, number] => {
    if (direction === 0) return origin >= min && origin <= max ? [-Infinity, Infinity] : [Infinity, -Infinity];
    const a = (min - origin) / direction;
    const b = (max - origin) / direction;
    return a <= b ? [a, b] : [b, a];
  };

  const [xEnter, xExit] = entry(box.x, box.x + box.w, anchor.x, dx);
  const [yEnter, yExit] = entry(box.y, box.y + box.h, anchor.y, dy);
  const tEnter = Math.max(xEnter, yEnter);
  const tExit = Math.min(xExit, yExit);
  if (tEnter > tExit || tEnter <= 0 || tEnter > 1) return null;
  return { x: anchor.x + dx * tEnter, y: anchor.y + dy * tEnter };
}

function overlaps(a: Box, b: Box, margin: number): boolean {
  return (
    a.x - margin < b.x + b.w &&
    a.x + a.w + margin > b.x &&
    a.y - margin < b.y + b.h &&
    a.y + a.h + margin > b.y
  );
}

function containsPoint(box: Box, p: ScreenPoint, margin: number): boolean {
  return (
    p.x > box.x - margin &&
    p.x < box.x + box.w + margin &&
    p.y > box.y - margin &&
    p.y < box.y + box.h + margin
  );
}

export interface Viewport {
  readonly width: number;
  readonly height: number;
}

function insideViewport(box: Box, viewport: Viewport | undefined): boolean {
  if (viewport === undefined) return true;
  return (
    box.x >= 0 && box.y >= 0 && box.x + box.w <= viewport.width && box.y + box.h <= viewport.height
  );
}

function clampToViewport(box: Box, viewport: Viewport | undefined): Box {
  if (viewport === undefined) return box;
  return {
    ...box,
    x: Math.min(Math.max(0, box.x), Math.max(0, viewport.width - box.w)),
    y: Math.min(Math.max(0, box.y), Math.max(0, viewport.height - box.h)),
  };
}

/**
 * Place every block. `measureWidth` returns the pixel width of a string in
 * the block font; the caller supplies it so this stays free of canvas state.
 * When a viewport is given, no block is allowed to hang off the edge of it.
 */
export function layoutDataBlocks(
  requests: readonly DataBlockRequest[],
  measureWidth: (text: string) => number,
  viewport?: Viewport,
): PlacedDataBlock[] {
  // Stable order: selected first so it always gets its preferred position,
  // then alphabetically, so the layout does not shuffle frame to frame.
  const ordered = [...requests].sort((a, b) => {
    if (a.selected !== b.selected) return a.selected ? -1 : 1;
    return a.id.localeCompare(b.id);
  });

  const placed: PlacedDataBlock[] = [];
  const anchors = requests.map((r) => r.anchor);

  for (const request of ordered) {
    const width =
      Math.max(...request.lines.map((line) => measureWidth(line))) + BLOCK_PADDING_PX * 2;
    const height = request.lines.length * LINE_HEIGHT_PX + BLOCK_PADDING_PX * 2;

    let chosen: Box | null = null;
    for (const dir of LEADER_DIRECTIONS) {
      const cx = request.anchor.x + dir.x * LEADER_LENGTH_PX;
      const cy = request.anchor.y + dir.y * LEADER_LENGTH_PX;
      const box: Box = {
        // The block sits away from the target, not centred on the leader tip.
        x: dir.x < 0 ? cx - width : cx,
        y: dir.y < 0 ? cy - height : cy - height / 2,
        w: width,
        h: height,
      };
      const clashesWithBlock = placed.some((p) => overlaps(box, p.box, 2));
      const clashesWithTarget = anchors.some((a) => containsPoint(box, a, 4));
      if (!clashesWithBlock && !clashesWithTarget && insideViewport(box, viewport)) {
        chosen = box;
        break;
      }
    }

    // Every direction is taken: fall back to the default rather than hide it,
    // pulled back onto the scope if it would otherwise run off the edge.
    const fallback: Box = {
      x: request.anchor.x + LEADER_LENGTH_PX * 0.707,
      y: request.anchor.y - LEADER_LENGTH_PX * 0.707 - height,
      w: width,
      h: height,
    };
    placed.push({ ...request, box: clampToViewport(chosen ?? fallback, viewport) });
  }

  return placed;
}
