/**
 * The aerodrome ground chart.
 *
 * A second, much larger-scale view of the field itself, drawn beside the
 * radar: runways with their designators, the taxiway system, the apron
 * outlines, and every stand. Aircraft near the ground are plotted on it at
 * their real positions, so a landing rollout or a departure waiting at the
 * holding point is somewhere you can actually look at.
 *
 * The radar is 60 NM across and this is about three, so the two cannot share
 * a camera. This view has its own: fixed on the aerodrome reference point,
 * scaled to fit the runways with a margin, and never panned — there is
 * nothing off the edge worth chasing.
 */

import { Aircraft } from '../sim/types.js';
import { Airspace } from '../sim/airspace.js';
import { Point } from '../sim/geo.js';
import {
  BLOCK_PADDING_PX,
  DataBlockRequest,
  layoutDataBlocks,
  leaderEndPoint,
} from './datablock.js';
import { THEME } from './theme.js';

/** Half-width of the charted area, in nautical miles either side of the ARP. */
const HALF_EXTENT_NM = 2.1;

/** Apron names shortened to what fits a panel this narrow. */
const SHORT_APRON = new Map<string, string>([
  ['Terminal 3', 'T3'],
  ['Terminal 1', 'T1'],
  ['Cargo', 'CGO'],
]);

/** Stands closer together than this on screen go unlabelled. */
const MIN_STAND_LABEL_GAP_PX = 16;

/** Aircraft above this height are not on the aerodrome in any useful sense. */
const CHART_CEILING_FT = 3000;

export class GroundChart {
  private readonly ctx: CanvasRenderingContext2D;
  private scale = 1;
  private originX = 0;
  private originY = 0;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly airspace: Airspace,
  ) {
    const ctx = canvas.getContext('2d');
    if (ctx === null) throw new Error('the ground chart canvas has no 2d context');
    this.ctx = ctx;
    this.resize();
  }

  /** Match the backing store to the element, so the chart is not blurred. */
  resize(): void {
    const ratio = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    this.canvas.width = Math.round(rect.width * ratio);
    this.canvas.height = Math.round(rect.height * ratio);
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

    // Fit the charted square into whichever dimension is tighter.
    this.scale = Math.min(rect.width, rect.height) / (HALF_EXTENT_NM * 2);
    this.originX = rect.width / 2;
    this.originY = rect.height / 2;
  }

  /** Local NM to canvas pixels. North is up, so y is inverted. */
  private toScreen(p: Point): { x: number; y: number } {
    return { x: this.originX + p.x * this.scale, y: this.originY - p.y * this.scale };
  }

  render(aircraft: readonly Aircraft[], selectedId: string | null): void {
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    const ctx = this.ctx;
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.fillStyle = THEME.background;
    ctx.fillRect(0, 0, rect.width, rect.height);

    this.drawAprons();
    this.drawTaxiways();
    this.drawRunways();
    this.drawStands();
    this.drawApronLabels();
    this.drawAircraft(aircraft, selectedId);
    this.drawScale(rect.height);
  }

  private drawAprons(): void {
    const ctx = this.ctx;
    for (const apron of this.airspace.groundChart.aprons) {
      if (apron.outline.length < 3) continue;
      ctx.beginPath();
      for (const [i, p] of apron.outline.entries()) {
        const s = this.toScreen(p);
        if (i === 0) ctx.moveTo(s.x, s.y);
        else ctx.lineTo(s.x, s.y);
      }
      ctx.closePath();
      ctx.fillStyle = 'rgba(45, 76, 152, 0.22)';
      ctx.fill();
      ctx.strokeStyle = THEME.ilsEdge;
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }

  /**
   * Apron names, drawn last.
   *
   * They sit on top of the runways and taxiways rather than under them: at
   * this scale the aprons overlap the runway designators, and a label half
   * hidden behind a runway is worse than one that plainly covers it.
   */
  private drawApronLabels(): void {
    const ctx = this.ctx;
    ctx.font = THEME.fontSmall;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    for (const apron of this.airspace.groundChart.aprons) {
      if (apron.outline.length < 3) continue;
      const cx = apron.outline.reduce((a, p) => a + p.x, 0) / apron.outline.length;
      const cy = apron.outline.reduce((a, p) => a + p.y, 0) / apron.outline.length;
      const c = this.toScreen({ x: cx, y: cy });
      const label = SHORT_APRON.get(apron.ident) ?? apron.ident.toUpperCase();

      // A slab of ground behind the text, so it reads over whatever it covers.
      const width = ctx.measureText(label).width;
      ctx.fillStyle = THEME.background;
      ctx.fillRect(c.x - width / 2 - 2, c.y - 5, width + 4, 10);

      ctx.fillStyle = THEME.chartLabel;
      ctx.fillText(label, c.x, c.y);
    }
  }

  private drawTaxiways(): void {
    const ctx = this.ctx;
    ctx.strokeStyle = THEME.centrelineTick;
    ctx.lineWidth = 1.6;
    ctx.lineCap = 'round';

    for (const taxiway of this.airspace.groundChart.taxiways) {
      if (taxiway.centreline.length < 2) continue;
      ctx.beginPath();
      for (const [i, p] of taxiway.centreline.entries()) {
        const s = this.toScreen(p);
        if (i === 0) ctx.moveTo(s.x, s.y);
        else ctx.lineTo(s.x, s.y);
      }
      ctx.stroke();

      // Designator at the midpoint of the first segment.
      const a = taxiway.centreline[0];
      const b = taxiway.centreline[1];
      if (a === undefined || b === undefined) continue;
      const mid = this.toScreen({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
      ctx.fillStyle = THEME.fixLabel;
      ctx.font = THEME.fontSmall;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(taxiway.ident, mid.x, mid.y);
    }
  }

  private drawRunways(): void {
    const ctx = this.ctx;
    // Runways come in pairs sharing one strip of tarmac; drawing every end
    // paints each strip twice, which is harmless and keeps this simple.
    for (const runway of this.airspace.runways) {
      const from = this.toScreen(runway.threshold);
      const to = this.toScreen(runway.stopEnd);

      ctx.strokeStyle = THEME.runway;
      ctx.lineWidth = 4;
      ctx.lineCap = 'butt';
      ctx.beginPath();
      ctx.moveTo(from.x, from.y);
      ctx.lineTo(to.x, to.y);
      ctx.stroke();

      // Designator just outside the threshold, turned to read along the
      // runway the way it is painted on the surface.
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      const length = Math.hypot(dx, dy) || 1;
      const lx = from.x - (dx / length) * 13;
      const ly = from.y - (dy / length) * 13;

      ctx.save();
      ctx.translate(lx, ly);
      let angle = Math.atan2(dy, dx);
      // Keep the text the right way up rather than upside down.
      if (angle > Math.PI / 2 || angle < -Math.PI / 2) angle += Math.PI;
      ctx.rotate(angle);
      ctx.fillStyle = THEME.runwayLabel;
      ctx.font = THEME.fontLabel;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(runway.ident, 0, 0);
      ctx.restore();
    }
  }

  private drawStands(): void {
    const ctx = this.ctx;
    for (const stand of this.airspace.groundChart.stands) {
      const s = this.toScreen(stand.position);
      ctx.fillStyle = THEME.aerodrome;
      ctx.fillRect(s.x - 1.5, s.y - 1.5, 3, 3);
    }

    // Stand numbers only when the stands are actually far enough apart to
    // carry them. In a side panel this narrow they are three pixels apart and
    // the labels overlap into a smear, so the rule is measured rather than
    // guessed: if the closest pair cannot fit a label between them, none are
    // drawn and the dots speak for themselves. Give the panel more room and
    // the numbers appear on their own.
    if (this.closestStandGapPx() < MIN_STAND_LABEL_GAP_PX) return;

    ctx.fillStyle = THEME.fixLabel;
    ctx.font = THEME.fontSmall;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (const stand of this.airspace.groundChart.stands) {
      const s = this.toScreen(stand.position);
      ctx.fillText(stand.ident, s.x, s.y + 4);
    }
  }

  /** Pixel distance between the two closest stands, at the current scale. */
  private closestStandGapPx(): number {
    const stands = this.airspace.groundChart.stands;
    let closest = Infinity;
    for (let i = 0; i < stands.length; i += 1) {
      for (let j = i + 1; j < stands.length; j += 1) {
        const a = stands[i];
        const b = stands[j];
        if (a === undefined || b === undefined) continue;
        const gap = Math.hypot(a.position.x - b.position.x, a.position.y - b.position.y);
        if (gap < closest) closest = gap;
      }
    }
    return closest * this.scale;
  }

  /**
   * Aircraft on or just above the aerodrome.
   *
   * The filter is height and position: anything above 3,000 ft or outside the
   * charted square is somewhere else, and drawing it here would be a lie
   * about where it is.
   *
   * Two aircraft on the field are often within a few pixels of each other —
   * one rolling out, one at the holding point — and printing each callsign at
   * a fixed offset put one on top of the other and made both unreadable. The
   * callsigns therefore go through the same placement the radar's data blocks
   * use: candidate positions around the target, the first that clashes with
   * nothing wins, and a leader line ties the label back to what it names.
   */
  private drawAircraft(aircraft: readonly Aircraft[], selectedId: string | null): void {
    const ctx = this.ctx;
    const rect = this.canvas.getBoundingClientRect();
    const elevation = this.airspace.airport.elevationFt;

    const onField = aircraft.filter(
      (ac) =>
        ac.altitudeFt - elevation <= CHART_CEILING_FT &&
        Math.abs(ac.position.x) <= HALF_EXTENT_NM &&
        Math.abs(ac.position.y) <= HALF_EXTENT_NM,
    );
    if (onField.length === 0) return;

    ctx.font = THEME.fontSmall;
    const requests: DataBlockRequest[] = onField.map((ac) => ({
      id: ac.id,
      anchor: this.toScreen(ac.position),
      lines: [ac.callsign],
      selected: ac.id === selectedId,
      severity: 'normal',
    }));
    const placed = layoutDataBlocks(requests, (text) => ctx.measureText(text).width, {
      width: rect.width,
      height: rect.height,
    });

    // Chevrons first, so no label is drawn under a later aircraft's symbol.
    for (const ac of onField) {
      const s = this.toScreen(ac.position);
      ctx.fillStyle = ac.id === selectedId ? THEME.targetSelected : THEME.target;

      // A chevron pointing where it is going, which on the ground is the
      // only thing that tells one direction of travel from the other.
      ctx.save();
      ctx.translate(s.x, s.y);
      ctx.rotate((ac.headingDeg * Math.PI) / 180);
      ctx.beginPath();
      ctx.moveTo(0, -5);
      ctx.lineTo(3.5, 4);
      ctx.lineTo(0, 2);
      ctx.lineTo(-3.5, 4);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }

    for (const block of placed) {
      const colour = block.selected ? THEME.targetSelected : THEME.target;
      const label = block.lines[0] ?? '';

      // The leader, drawn only when the label has been pushed far enough away
      // to need one. leaderEndPoint stops it at the box edge rather than
      // running it through the text.
      const end = leaderEndPoint(block.anchor, block.box);
      if (end !== null) {
        ctx.strokeStyle = THEME.leader;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(block.anchor.x, block.anchor.y);
        ctx.lineTo(end.x, end.y);
        ctx.stroke();
      }

      // Ground behind the text: the chart underneath is busy, and a callsign
      // over a runway edge is otherwise hard to read.
      const width = ctx.measureText(label).width;
      ctx.fillStyle = THEME.background;
      ctx.fillRect(block.box.x, block.box.y, width + BLOCK_PADDING_PX * 2, block.box.h);

      ctx.fillStyle = colour;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, block.box.x + BLOCK_PADDING_PX, block.box.y + block.box.h / 2);
    }
  }

  private drawScale(height: number): void {
    const ctx = this.ctx;
    const oneNm = this.scale;
    const y = height - 12;

    ctx.strokeStyle = THEME.scaleBar;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(10, y);
    ctx.lineTo(10 + oneNm, y);
    ctx.moveTo(10, y - 3);
    ctx.lineTo(10, y + 3);
    ctx.moveTo(10 + oneNm, y - 3);
    ctx.lineTo(10 + oneNm, y + 3);
    ctx.stroke();

    ctx.fillStyle = THEME.scaleBar;
    ctx.font = THEME.fontSmall;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'bottom';
    ctx.fillText('1 NM', 10, y - 5);
  }
}
