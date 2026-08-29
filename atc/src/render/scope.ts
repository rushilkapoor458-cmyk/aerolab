/**
 * The radar scope. Canvas only: it reads the simulation and draws it, and
 * never changes it.
 *
 * Drawn back to front — ground, map, procedures, traffic, labels — so the
 * things a controller reads sit on top of the things they only glance at.
 */

import { Airspace, Runway } from '../sim/airspace.js';
import { Alert } from '../sim/safety.js';
import { Point, bearingDeg, distanceNm, formatBearing, movePoint, normalizeDeg } from '../sim/geo.js';
import { Aircraft } from '../sim/types.js';
import { Simulation } from '../sim/world.js';
import { toRadians } from '../sim/units.js';
import { Camera, ScreenPoint } from './camera.js';
import {
  DataBlockRequest,
  DataBlockSeverity,
  LINE_HEIGHT_PX,
  BLOCK_PADDING_PX,
  dataBlockLines,
  dataBlockSeverity,
  layoutDataBlocks,
  leaderEndPoint,
} from './datablock.js';
import { THEME } from './theme.js';

export interface Ruler {
  readonly from: Point;
  readonly to: Point;
}

export interface ScopeView {
  readonly selectedId: string | null;
  readonly ruler: Ruler | null;
  readonly alerts: readonly Alert[];
}

const RANGE_RINGS_NM = [10, 20, 30, 40, 50, 60];
/** Rings drawn a shade brighter, as a coarse scale. */
const MAJOR_RINGS_NM = new Set([20, 40, 60]);
const COMPASS_RADIUS_NM = 60;
const CENTRELINE_LENGTH_NM = 12;
const SPEED_VECTOR_SEC = 60;
const TARGET_HALF_PX = 3.5;
/** Feet in a nautical mile, for drawing runways at their paved width. */
const FT_PER_NM = 6076.11548556;
/** Zoom at which runway designators become readable. */
const RUNWAY_LABEL_ZOOM_PX_PER_NM = 14;
/** Zoom at which route legs carry their course and distance. */
const LEG_LABEL_ZOOM_PX_PER_NM = 5;
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

  /**
   * Aircraft the radar is painting. One still at the holding point is the
   * tower's business and does not appear until it starts rolling.
   */
  private get painted(): readonly Aircraft[] {
    return this.sim.aircraft.filter((ac) => ac.ground === null || ac.ground === 'takeoff');
  }

  /** The aircraft under a screen point, if any. */
  aircraftAt(screen: ScreenPoint): Aircraft | null {
    let best: Aircraft | null = null;
    let bestDistance = PICK_RADIUS_PX;
    for (const ac of this.painted) {
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
    this.drawCompassRose();
    this.drawBoundary(airspace);
    this.drawApproaches(airspace);
    this.drawRunways(airspace);
    this.drawAerodrome();
    this.drawFixes(airspace);

    const painted = this.painted;
    const selected = painted.find((a) => a.id === view.selectedId) ?? null;
    if (selected !== null) this.drawRoute(selected, airspace);
    for (const ac of painted) {
      if (ac.approach !== null) this.drawApproachPath(ac, airspace);
    }

    this.drawConflicts(view.alerts);
    for (const ac of painted) this.drawTarget(ac, ac.id === view.selectedId);

    this.drawDataBlocks(view.selectedId, view.alerts);
    if (view.ruler !== null) this.drawRuler(view.ruler);
    this.drawScaleBar();
  }

  /* --------------------------------------------------------------- layers */

  private drawRangeRings(): void {
    const { ctx, camera } = this;
    const centre = camera.toScreen({ x: 0, y: 0 });
    ctx.save();
    ctx.lineWidth = 1;
    for (const nm of RANGE_RINGS_NM) {
      ctx.strokeStyle = MAJOR_RINGS_NM.has(nm) ? THEME.rangeRingMajor : THEME.rangeRing;
      ctx.setLineDash(MAJOR_RINGS_NM.has(nm) ? [] : [2, 7]);
      ctx.beginPath();
      ctx.arc(centre.x, centre.y, nm * camera.pxPerNm, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    // Range labels, stacked up the north radial so they read like a ruler.
    ctx.font = THEME.fontSmall;
    ctx.fillStyle = THEME.rangeRingLabel;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    for (const nm of RANGE_RINGS_NM) {
      const y = centre.y - nm * camera.pxPerNm;
      if (y < 12 || y > camera.heightPx) continue;
      ctx.fillText(String(nm), centre.x, y - 3);
    }
    ctx.restore();
  }

  /** Ticks every ten degrees round the outer ring, labelled every thirty. */
  private drawCompassRose(): void {
    const { ctx, camera } = this;
    const radiusPx = COMPASS_RADIUS_NM * camera.pxPerNm;
    // Below a certain zoom the rose is off screen and just wastes ink.
    if (radiusPx < 60) return;
    const centre = camera.toScreen({ x: 0, y: 0 });

    ctx.save();
    ctx.font = THEME.fontSmall;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (let magnetic = 0; magnetic < 360; magnetic += 10) {
      const trueBearing = this.sim.airspace.toTrue(magnetic);
      const r = toRadians(trueBearing);
      const major = magnetic % 30 === 0;
      const length = major ? 10 : 5;
      const outer = radiusPx;
      const inner = radiusPx - length;
      ctx.strokeStyle = major ? THEME.compassTickMajor : THEME.compassTick;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(centre.x + Math.sin(r) * inner, centre.y - Math.cos(r) * inner);
      ctx.lineTo(centre.x + Math.sin(r) * outer, centre.y - Math.cos(r) * outer);
      ctx.stroke();

      if (major) {
        const labelRadius = radiusPx + 11;
        ctx.fillStyle = THEME.compassLabel;
        ctx.fillText(
          String(magnetic === 0 ? 36 : magnetic / 10).padStart(2, '0'),
          centre.x + Math.sin(r) * labelRadius,
          centre.y - Math.cos(r) * labelRadius,
        );
      }
    }
    ctx.restore();
  }

  private drawBoundary(airspace: Airspace): void {
    const { ctx, camera } = this;
    const boundary = airspace.sector.boundary;
    if (boundary.length < 2) return;
    ctx.save();
    ctx.beginPath();
    boundary.forEach((p, i) => {
      const s = camera.toScreen(p);
      if (i === 0) ctx.moveTo(s.x, s.y);
      else ctx.lineTo(s.x, s.y);
    });
    ctx.closePath();
    // A soft halo under the line reads as an area rather than a scratch.
    ctx.strokeStyle = THEME.boundaryGlow;
    ctx.lineWidth = 5;
    ctx.stroke();
    ctx.strokeStyle = THEME.boundary;
    ctx.lineWidth = 1.4;
    ctx.stroke();
    ctx.restore();
  }

  /** Runways in use: the arrival runway plus any an aircraft is cleared to. */
  private runwaysInUse(airspace: Airspace): Runway[] {
    const idents = new Set<string>([this.sim.runways.arrival]);
    for (const ac of this.sim.aircraft) {
      if (ac.approach !== null) idents.add(ac.approach.runway);
      if (ac.role === 'departure' && ac.departureRunway !== null) idents.add(ac.departureRunway);
    }
    const runways: Runway[] = [];
    for (const ident of idents) {
      const runway = airspace.runway(ident);
      if (runway !== undefined) runways.push(runway);
    }
    return runways;
  }

  /** Extended centreline, mile ticks, localiser splay and the final fix. */
  private drawApproaches(airspace: Airspace): void {
    const { ctx, camera } = this;
    ctx.save();
    for (const runway of this.runwaysInUse(airspace)) {
      const approach = airspace.approachForRunway(runway.ident);
      const outbound = (runway.trueHeadingDeg + 180) % 360;
      const threshold = camera.toScreen(runway.threshold);

      if (approach !== undefined) {
        const range = approach.interceptRangeNm;
        const half = 2.5; // Localiser course sector, degrees either side.
        const left = camera.toScreen(movePoint(runway.threshold, (outbound - half + 360) % 360, range));
        const right = camera.toScreen(movePoint(runway.threshold, (outbound + half) % 360, range));
        ctx.fillStyle = THEME.ilsCone;
        ctx.beginPath();
        ctx.moveTo(threshold.x, threshold.y);
        ctx.lineTo(left.x, left.y);
        ctx.lineTo(right.x, right.y);
        ctx.closePath();
        ctx.fill();
        ctx.strokeStyle = THEME.ilsEdge;
        ctx.lineWidth = 0.8;
        ctx.stroke();
      }

      const far = camera.toScreen(movePoint(runway.threshold, outbound, CENTRELINE_LENGTH_NM));
      ctx.strokeStyle = THEME.centreline;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(threshold.x, threshold.y);
      ctx.lineTo(far.x, far.y);
      ctx.stroke();

      // One tick per nautical mile, longer every five.
      const across = (runway.trueHeadingDeg + 90) % 360;
      ctx.strokeStyle = THEME.centrelineTick;
      for (let nm = 1; nm <= CENTRELINE_LENGTH_NM; nm++) {
        const halfNm = nm % 5 === 0 ? 0.6 : 0.3;
        const on = movePoint(runway.threshold, outbound, nm);
        const a = camera.toScreen(movePoint(on, across, halfNm));
        const b = camera.toScreen(movePoint(on, (across + 180) % 360, halfNm));
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }

      // The final approach fix, where the descent begins.
      const faf = approach === undefined ? undefined : airspace.fix(approach.finalApproachFix);
      if (faf !== undefined && approach !== undefined) {
        const s = camera.toScreen(faf.position);
        ctx.strokeStyle = THEME.fafMark;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.arc(s.x, s.y, 4, 0, Math.PI * 2);
        ctx.stroke();
        // The crossing altitude, as the plate gives it.
        ctx.font = THEME.fontSmall;
        ctx.fillStyle = THEME.chartLabel;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(`${approach.fafAltitudeFt}`, s.x, s.y + 6);
      }

      // The localiser course, against the centreline, as the plate gives it.
      if (approach !== undefined) {
        const at = camera.toScreen(movePoint(runway.threshold, outbound, CENTRELINE_LENGTH_NM * 0.62));
        ctx.font = THEME.fontLabel;
        ctx.fillStyle = THEME.chartLabel;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText(
          `ILS ${runway.ident}  ${formatBearing(approach.localiserCourseMagneticDeg)}\u00b0`,
          at.x,
          at.y - 6,
        );
      }
    }
    ctx.restore();
  }

  private drawRunways(airspace: Airspace): void {
    const { ctx, camera } = this;
    ctx.save();
    ctx.strokeStyle = THEME.runway;
    ctx.fillStyle = THEME.runway;
    ctx.lineCap = 'butt';

    for (const runway of airspace.runways) {
      const a = camera.toScreen(runway.threshold);
      const b = camera.toScreen(runway.stopEnd);
      // Draw the paved width where the zoom can show it, a hairline otherwise.
      ctx.lineWidth = Math.max(1.6, (runway.widthFt / FT_PER_NM) * camera.pxPerNm);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }

    // Designators, once there is room to read them.
    if (camera.pxPerNm >= RUNWAY_LABEL_ZOOM_PX_PER_NM) {
      ctx.font = THEME.fontSmall;
      ctx.fillStyle = THEME.runwayLabel;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const across = 0.22; // Offset the label clear of the paved surface, in NM.
      for (const runway of airspace.runways) {
        const side = (runway.trueHeadingDeg + 90) % 360;
        const at = movePoint(
          movePoint(runway.threshold, (runway.trueHeadingDeg + 180) % 360, 0.12),
          side,
          across,
        );
        const s = camera.toScreen(at);
        ctx.fillText(runway.ident, s.x, s.y);
      }
    }
    ctx.restore();
  }

  /** The aerodrome reference point, so the field is findable at any zoom. */
  private drawAerodrome(): void {
    const { ctx, camera } = this;
    const s = camera.toScreen({ x: 0, y: 0 });
    ctx.save();
    ctx.strokeStyle = THEME.aerodrome;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(s.x, s.y, 3, 0, Math.PI * 2);
    ctx.stroke();
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
      const boundary = fix.type === 'boundary';
      ctx.strokeStyle = boundary ? THEME.fixBoundary : THEME.fix;
      ctx.lineWidth = 1;
      ctx.beginPath();
      if (boundary) {
        // Entry points get a larger triangle so they stand out at a glance.
        ctx.moveTo(s.x, s.y - 5);
        ctx.lineTo(s.x + 4.5, s.y + 3);
        ctx.lineTo(s.x - 4.5, s.y + 3);
      } else {
        ctx.moveTo(s.x, s.y - 3.2);
        ctx.lineTo(s.x + 3.2, s.y);
        ctx.lineTo(s.x, s.y + 3.2);
        ctx.lineTo(s.x - 3.2, s.y);
      }
      ctx.closePath();
      ctx.stroke();
      ctx.fillStyle = boundary ? THEME.fixBoundary : THEME.fixLabel;
      ctx.fillText(fix.name, s.x + 7, s.y + 1);
    }
    ctx.restore();
  }

  /**
   * The selected aircraft's route, drawn the way a procedure is drawn on a
   * plate: the track, the course and distance of each leg, and the published
   * restriction at each fix it is going to cross.
   */
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
    ctx.setLineDash([]);

    if (camera.pxPerNm >= LEG_LABEL_ZOOM_PX_PER_NM) {
      ctx.font = THEME.fontSmall;
      ctx.fillStyle = THEME.chartLabel;
      ctx.textAlign = 'center';

      for (let i = 1; i < points.length; i++) {
        const from = points[i - 1];
        const to = points[i];
        if (from === undefined || to === undefined) continue;

        // Course and distance, against the middle of the leg.
        const course = airspace.toMagnetic(bearingDeg(from, to));
        const legNm = distanceNm(from, to);
        const mid = camera.toScreen({ x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 });
        ctx.textBaseline = 'bottom';
        ctx.fillText(`${formatBearing(course)}\u00b0  ${legNm.toFixed(1)}`, mid.x, mid.y - 3);

        // The published restriction at the fix this leg ends on.
        const name = names[i - 1];
        const restriction =
          name === undefined || ac.procedure === null
            ? undefined
            : airspace.procedureLeg(ac.procedure, name);
        if (restriction === undefined) continue;
        const parts: string[] = [];
        if (restriction.altitudeConstraint !== null) {
          const c = restriction.altitudeConstraint;
          const mark = c.type === 'at_or_below' ? '\u2264' : c.type === 'at_or_above' ? '\u2265' : '';
          parts.push(`${mark}${c.altitudeFt}`);
        }
        if (restriction.speedConstraint !== null) parts.push(`${restriction.speedConstraint.speedKt}kt`);
        if (parts.length === 0) continue;
        const at = camera.toScreen(to);
        ctx.textBaseline = 'top';
        ctx.fillText(parts.join('  '), at.x, at.y + 12);
      }
    }
    ctx.restore();
  }

  /** A line from an aircraft cleared for an approach to its threshold. */
  private drawApproachPath(ac: Aircraft, airspace: Airspace): void {
    const runway = ac.approach === null ? undefined : airspace.runway(ac.approach.runway);
    if (runway === undefined) return;
    const { ctx, camera } = this;
    const a = camera.toScreen(ac.position);
    const b = camera.toScreen(runway.threshold);
    ctx.save();
    ctx.strokeStyle = THEME.approachPath;
    ctx.globalAlpha = ac.approach?.localiserCaptured === true ? 0.75 : 0.35;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 5]);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
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
      ctx.globalAlpha = 0.15 + (0.5 * i) / Math.max(1, ac.history.length - 1);
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

    // Target symbol, with just enough bloom to read as a returned signal.
    const colour = selected
      ? THEME.targetSelected
      : ac.fuelState === 'emergency'
        ? THEME.dataBlockAlert
        : ac.handedOff
          ? THEME.dataBlockDim
          : THEME.target;
    ctx.strokeStyle = colour;
    ctx.shadowColor = THEME.targetGlow;
    ctx.shadowBlur = selected ? 8 : 4;
    ctx.lineWidth = selected ? 2 : 1.4;
    ctx.strokeRect(s.x - TARGET_HALF_PX, s.y - TARGET_HALF_PX, TARGET_HALF_PX * 2, TARGET_HALF_PX * 2);
    ctx.shadowBlur = 0;
    if (selected) {
      ctx.beginPath();
      ctx.arc(s.x, s.y, TARGET_HALF_PX + 5, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }

  /**
   * A line between the two aircraft of every conflict, flashing so it catches
   * the eye away from where the controller happens to be looking.
   */
  private drawConflicts(alerts: readonly Alert[]): void {
    const pairs = alerts.filter((a) => a.aircraftIds.length === 2);
    if (pairs.length === 0) return;
    const { ctx, camera } = this;
    const now = performance.now();

    ctx.save();
    ctx.font = THEME.fontLabel;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    for (const alert of pairs) {
      const first = this.painted.find((x) => x.id === alert.aircraftIds[0]);
      const second = this.painted.find((x) => x.id === alert.aircraftIds[1]);
      if (first === undefined || second === undefined) continue;

      const a = camera.toScreen(first.position);
      const b = camera.toScreen(second.position);
      const warning = alert.severity === 'warning';
      // Warnings flash faster than cautions, so the two never read the same.
      const period = warning ? 700 : 1200;
      const phase = (now % period) / period;
      ctx.globalAlpha = 0.45 + 0.55 * Math.abs(Math.sin(phase * Math.PI));
      ctx.strokeStyle = warning ? THEME.dataBlockAlert : THEME.dataBlockCaution;
      ctx.lineWidth = warning ? 1.8 : 1.2;
      ctx.setLineDash(warning ? [] : [6, 4]);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      ctx.setLineDash([]);

      const distance = distanceNm(first.position, second.position);
      const vertical = Math.abs(first.altitudeFt - second.altitudeFt);
      ctx.fillStyle = warning ? THEME.dataBlockAlert : THEME.dataBlockCaution;
      ctx.fillText(
        `${distance.toFixed(1)} / ${Math.round(vertical)}`,
        (a.x + b.x) / 2,
        (a.y + b.y) / 2 - 4,
      );
    }
    ctx.globalAlpha = 1;
    ctx.restore();
  }

  private drawDataBlocks(selectedId: string | null, alerts: readonly Alert[]): void {
    const { ctx, camera } = this;
    ctx.save();
    ctx.font = THEME.fontBlock;
    ctx.textBaseline = 'top';
    ctx.textAlign = 'left';

    const worst = new Map<string, 'caution' | 'warning'>();
    for (const alert of alerts) {
      for (const id of alert.aircraftIds) {
        if (alert.severity === 'warning' || worst.get(id) === undefined) {
          worst.set(id, alert.severity);
        }
      }
    }

    const requests: DataBlockRequest[] = this.painted.map((ac) => ({
      id: ac.id,
      anchor: camera.toScreen(ac.position),
      lines: dataBlockLines(ac, this.sim.airspace),
      selected: ac.id === selectedId,
      severity: dataBlockSeverity(ac, worst.get(ac.id) ?? null),
    }));
    const measure = (text: string): number => ctx.measureText(text).width;
    const viewport = { width: camera.widthPx, height: camera.heightPx };

    for (const block of layoutDataBlocks(requests, measure, viewport)) {
      const colour = block.selected ? THEME.dataBlockSelected : severityColour(block.severity);
      // The leader stops where it meets the block, so it never strikes through
      // the text — which matters most for a block pushed against the edge.
      const end = leaderEndPoint(block.anchor, block.box);
      if (end !== null) {
        ctx.strokeStyle = THEME.leader;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(block.anchor.x, block.anchor.y);
        ctx.lineTo(end.x, end.y);
        ctx.stroke();
      }

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
    const label = `${range.toFixed(1)} NM  ${Math.round(normalizeDeg(bearing)).toString().padStart(3, '0')}°M`;
    ctx.fillText(label, b.x + 8, b.y - 4);
    ctx.restore();
  }

  /** A bar in the corner giving the current scale, as a chart would. */
  private drawScaleBar(): void {
    const { ctx, camera } = this;
    const target = 110; // Aim for a bar about this many pixels long.
    const candidates = [1, 2, 5, 10, 20, 50];
    const nm =
      candidates.find((c) => c * camera.pxPerNm >= target) ?? candidates[candidates.length - 1] ?? 10;
    const lengthPx = nm * camera.pxPerNm;
    const x = 16;
    const y = camera.heightPx - 18;

    ctx.save();
    ctx.strokeStyle = THEME.scaleBar;
    ctx.fillStyle = THEME.scaleBar;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, y - 4);
    ctx.lineTo(x, y);
    ctx.lineTo(x + lengthPx, y);
    ctx.lineTo(x + lengthPx, y - 4);
    ctx.stroke();
    ctx.font = THEME.fontSmall;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'bottom';
    ctx.fillText(`${nm} NM`, x, y - 6);
    ctx.restore();
  }
}

function severityColour(severity: DataBlockSeverity): string {
  switch (severity) {
    case 'alert':
      return THEME.dataBlockAlert;
    case 'caution':
      return THEME.dataBlockCaution;
    case 'dim':
      return THEME.dataBlockDim;
    default:
      return THEME.dataBlock;
  }
}
