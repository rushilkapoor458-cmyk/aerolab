/**
 * The radar scope. Canvas only: it reads the simulation and draws it, and
 * never changes it.
 */

import { Airspace } from '../sim/airspace.js';
import { Point, bearingDeg, distanceNm, movePoint } from '../sim/geo.js';
import { Aircraft } from '../sim/types.js';
import { Simulation } from '../sim/world.js';
import { Camera, ScreenPoint } from './camera.js';
import {
  DataBlockRequest,
  LINE_HEIGHT_PX,
  BLOCK_PADDING_PX,
  dataBlockLines,
  layoutDataBlocks,
} from './datablock.js';
import { THEME } from './theme.js';

export interface Ruler {
  readonly from: Point;
  readonly to: Point;
}

export interface ScopeView {
  readonly selectedId: string | null;
  readonly ruler: Ruler | null;
}

const RANGE_RINGS_NM = [10, 20, 30, 40, 50, 60];
const CENTRELINE_LENGTH_NM = 10;
const SPEED_VECTOR_SEC = 60;
const TARGET_HALF_PX = 3.5;
/** How close in pixels a click has to be to pick up a target. */
export const PICK_RADIUS_PX = 14;

export class RadarScope {
  readonly camera = new Camera();
  private readonly ctx: CanvasRenderingContext2D;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly sim: Simulation,
  ) {
    const ctx = canvas.getContext('2d');
    if (ctx === null) throw new Error('This browser did not give us a 2D canvas context.');
    this.ctx = ctx;
    this.resize();
    this.camera.fitRadius(this.sim.airspace.sector.radiusNm * 0.95);
  }

  /** Match the backing store to the element size and the device pixel ratio. */
  resize(): void {
    const dpr = window.devicePixelRatio || 1;
    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    this.canvas.width = Math.max(1, Math.round(width * dpr));
    this.canvas.height = Math.max(1, Math.round(height * dpr));
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.camera.resize(width, height);
  }

  /** The aircraft under a screen point, if any. */
  aircraftAt(screen: ScreenPoint): Aircraft | null {
    let best: Aircraft | null = null;
    let bestDistance = PICK_RADIUS_PX;
    for (const ac of this.sim.aircraft) {
      const p = this.camera.toScreen(ac.position);
      const d = Math.hypot(p.x - screen.x, p.y - screen.y);
      if (d < bestDistance) {
        bestDistance = d;
        best = ac;
      }
    }
    return best;
  }

  render(view: ScopeView): void {
    const { ctx, camera } = this;
    const airspace = this.sim.airspace;

    ctx.fillStyle = THEME.background;
    ctx.fillRect(0, 0, camera.widthPx, camera.heightPx);

    this.drawRangeRings();
    this.drawBoundary(airspace);
    this.drawRunways(airspace);
    this.drawFixes(airspace);

    const selected = this.sim.aircraft.find((a) => a.id === view.selectedId) ?? null;
    if (selected !== null) this.drawRoute(selected, airspace);

    for (const ac of this.sim.aircraft) this.drawTarget(ac, ac.id === view.selectedId);

    this.drawDataBlocks(view.selectedId);
    if (view.ruler !== null) this.drawRuler(view.ruler);
  }

  /* --------------------------------------------------------------- layers */

  private drawRangeRings(): void {
    const { ctx, camera } = this;
    const centre = camera.toScreen({ x: 0, y: 0 });
    ctx.save();
    ctx.strokeStyle = THEME.grid;
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 6]);
    for (const nm of RANGE_RINGS_NM) {
      ctx.beginPath();
      ctx.arc(centre.x, centre.y, nm * camera.pxPerNm, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.fillStyle = THEME.rangeRingLabel;
    ctx.font = THEME.fontSmall;
    ctx.textAlign = 'center';
    for (const nm of RANGE_RINGS_NM) {
      ctx.fillText(String(nm), centre.x, centre.y - nm * camera.pxPerNm - 3);
    }
    ctx.restore();
  }

  private drawBoundary(airspace: Airspace): void {
    const { ctx, camera } = this;
    const boundary = airspace.sector.boundary;
    if (boundary.length < 2) return;
    ctx.save();
    ctx.strokeStyle = THEME.boundary;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    boundary.forEach((p, i) => {
      const s = camera.toScreen(p);
      if (i === 0) ctx.moveTo(s.x, s.y);
      else ctx.lineTo(s.x, s.y);
    });
    ctx.closePath();
    ctx.stroke();
    ctx.restore();
  }

  private drawRunways(airspace: Airspace): void {
    const { ctx, camera } = this;
    ctx.save();

    // Paved surfaces.
    ctx.strokeStyle = THEME.runway;
    ctx.lineWidth = 2;
    for (const runway of airspace.runways) {
      const a = camera.toScreen(runway.threshold);
      const b = camera.toScreen(runway.stopEnd);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }

    // Extended centreline, tick marks and localiser splay for the runway in use.
    const active = airspace.runway(this.sim.runways.arrival);
    if (active !== undefined) {
      const outbound = (active.trueHeadingDeg + 180) % 360;
      const far = movePoint(active.threshold, outbound, CENTRELINE_LENGTH_NM);
      const t = camera.toScreen(active.threshold);
      const f = camera.toScreen(far);

      ctx.strokeStyle = THEME.centreline;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(t.x, t.y);
      ctx.lineTo(f.x, f.y);
      ctx.stroke();

      // One tick per nautical mile, drawn across the centreline.
      ctx.strokeStyle = THEME.centrelineTick;
      const acrossLeft = (active.trueHeadingDeg + 90) % 360;
      const tickHalfNm = 0.35;
      for (let nm = 1; nm <= CENTRELINE_LENGTH_NM; nm++) {
        const on = movePoint(active.threshold, outbound, nm);
        const p1 = camera.toScreen(movePoint(on, acrossLeft, tickHalfNm));
        const p2 = camera.toScreen(movePoint(on, (acrossLeft + 180) % 360, tickHalfNm));
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
      }

      const approach = airspace.approachForRunway(active.ident);
      if (approach !== undefined) {
        const range = approach.interceptRangeNm;
        const half = 3; // Localiser course sector, degrees either side.
        const left = movePoint(active.threshold, (outbound - half + 360) % 360, range);
        const right = movePoint(active.threshold, (outbound + half) % 360, range);
        const l = camera.toScreen(left);
        const r = camera.toScreen(right);
        ctx.fillStyle = THEME.ilsCone;
        ctx.beginPath();
        ctx.moveTo(t.x, t.y);
        ctx.lineTo(l.x, l.y);
        ctx.lineTo(r.x, r.y);
        ctx.closePath();
        ctx.fill();
      }
    }
    ctx.restore();
  }

  private drawFixes(airspace: Airspace): void {
    const { ctx, camera } = this;
    ctx.save();
    ctx.font = THEME.fontSmall;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    for (const fix of airspace.fixes) {
      const s = camera.toScreen(fix.position);
      if (s.x < -40 || s.y < -40 || s.x > camera.widthPx + 40 || s.y > camera.heightPx + 40) continue;
      ctx.strokeStyle = THEME.fix;
      ctx.lineWidth = 1;
      ctx.beginPath();
      if (fix.type === 'boundary') {
        // Boundary fixes get a larger triangle so entry points stand out.
        ctx.moveTo(s.x, s.y - 5);
        ctx.lineTo(s.x + 4.5, s.y + 3);
        ctx.lineTo(s.x - 4.5, s.y + 3);
      } else {
        ctx.moveTo(s.x, s.y - 3.5);
        ctx.lineTo(s.x + 3.5, s.y);
        ctx.lineTo(s.x, s.y + 3.5);
        ctx.lineTo(s.x - 3.5, s.y);
      }
      ctx.closePath();
      ctx.stroke();
      ctx.fillStyle = THEME.fixLabel;
      ctx.fillText(fix.name, s.x + 7, s.y + 1);
    }
    ctx.restore();
  }

  private drawRoute(ac: Aircraft, airspace: Airspace): void {
    const { ctx, camera } = this;
    const names: string[] = [];
    if (ac.clearance.lateralMode === 'direct' && ac.clearance.directFix !== null) {
      names.push(ac.clearance.directFix);
    }
    names.push(...ac.route);
    const points: Point[] = [ac.position];
    for (const name of names) {
      const fix = airspace.fix(name);
      if (fix !== undefined) points.push(fix.position);
    }
    if (points.length < 2) return;

    ctx.save();
    ctx.strokeStyle = THEME.route;
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    points.forEach((p, i) => {
      const s = camera.toScreen(p);
      if (i === 0) ctx.moveTo(s.x, s.y);
      else ctx.lineTo(s.x, s.y);
    });
    ctx.stroke();
    ctx.restore();
  }

  private drawTarget(ac: Aircraft, selected: boolean): void {
    const { ctx, camera } = this;
    const s = camera.toScreen(ac.position);

    ctx.save();
    // History: oldest dot dimmest.
    for (let i = 0; i < ac.history.length - 1; i++) {
      const p = ac.history[i];
      if (p === undefined) continue;
      const hs = camera.toScreen(p);
      ctx.globalAlpha = 0.18 + (0.5 * i) / Math.max(1, ac.history.length - 1);
      ctx.fillStyle = THEME.history;
      ctx.fillRect(hs.x - 1, hs.y - 1, 2, 2);
    }
    ctx.globalAlpha = 1;

    // Speed vector: where it will be in sixty seconds.
    const ahead = movePoint(ac.position, ac.trueTrackDeg, (ac.groundspeedKt / 3600) * SPEED_VECTOR_SEC);
    const a = camera.toScreen(ahead);
    ctx.strokeStyle = THEME.vector;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(s.x, s.y);
    ctx.lineTo(a.x, a.y);
    ctx.stroke();

    // Target symbol.
    ctx.strokeStyle = selected ? THEME.targetSelected : THEME.target;
    ctx.lineWidth = selected ? 2 : 1.4;
    ctx.strokeRect(s.x - TARGET_HALF_PX, s.y - TARGET_HALF_PX, TARGET_HALF_PX * 2, TARGET_HALF_PX * 2);
    if (selected) {
      ctx.beginPath();
      ctx.arc(s.x, s.y, TARGET_HALF_PX + 5, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }

  private drawDataBlocks(selectedId: string | null): void {
    const { ctx, camera } = this;
    ctx.save();
    ctx.font = THEME.fontMono;
    ctx.textBaseline = 'top';
    ctx.textAlign = 'left';

    const requests: DataBlockRequest[] = this.sim.aircraft.map((ac) => ({
      id: ac.id,
      anchor: camera.toScreen(ac.position),
      lines: dataBlockLines(ac, this.sim.airspace),
      selected: ac.id === selectedId,
    }));
    const measure = (text: string): number => ctx.measureText(text).width;

    const viewport = { width: camera.widthPx, height: camera.heightPx };
    for (const block of layoutDataBlocks(requests, measure, viewport)) {
      const colour = block.selected ? THEME.dataBlockSelected : THEME.dataBlock;
      // Leader from the target to the nearest corner of the block.
      const targetX = clampTo(block.anchor.x, block.box.x, block.box.x + block.box.w);
      const targetY = clampTo(block.anchor.y, block.box.y, block.box.y + block.box.h);
      ctx.strokeStyle = THEME.leader;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(block.anchor.x, block.anchor.y);
      ctx.lineTo(targetX, targetY);
      ctx.stroke();

      ctx.fillStyle = colour;
      block.lines.forEach((line, i) => {
        ctx.fillText(
          line,
          block.box.x + BLOCK_PADDING_PX,
          block.box.y + BLOCK_PADDING_PX + i * LINE_HEIGHT_PX,
        );
      });
    }
    ctx.restore();
  }

  private drawRuler(ruler: Ruler): void {
    const { ctx, camera } = this;
    const a = camera.toScreen(ruler.from);
    const b = camera.toScreen(ruler.to);
    const range = distanceNm(ruler.from, ruler.to);
    const bearing = this.sim.airspace.toMagnetic(bearingDeg(ruler.from, ruler.to));

    ctx.save();
    ctx.strokeStyle = THEME.ruler;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = THEME.ruler;
    ctx.font = THEME.fontLabel;
    ctx.textBaseline = 'bottom';
    ctx.textAlign = 'left';
    const label = `${range.toFixed(1)} NM / ${Math.round(bearing).toString().padStart(3, '0')}°M`;
    ctx.fillText(label, b.x + 8, b.y - 4);
    ctx.restore();
  }
}

function clampTo(value: number, min: number, max: number): number {
  return value < min ? min : value > max ? max : value;
}
