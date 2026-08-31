/**
 * The aerodrome ground chart.
 *
 * A second, much larger-scale view of the field itself, drawn beside the
 * radar: runway pavement with thresholds and designators, the taxiway system,
 * the apron outlines and every stand. Aircraft on or just above the field are
 * plotted at their real positions, so a landing rollout or a departure waiting
 * at the holding point is somewhere you can actually look at.
 *
 * The radar is 60 NM across and this is about four, so the two cannot share a
 * camera. This view has its own: fixed on the aerodrome reference point,
 * scaled to fit the runways with a margin, and never panned — there is nothing
 * off the edge worth chasing.
 *
 * It is drawn the way a printed aerodrome chart is drawn, with one deliberate
 * departure from scale. A real runway is about 200 ft wide, which at this
 * zoom is under two pixels: true to scale and invisible. Published charts
 * exaggerate pavement width for exactly this reason, and so does this one —
 * everything else, positions and lengths included, is to scale.
 */

import { Aircraft } from '../sim/types.js';
import { Airspace, Runway } from '../sim/airspace.js';
import { Point } from '../sim/geo.js';
import {
  BLOCK_PADDING_PX,
  Box,
  DataBlockRequest,
  layoutDataBlocks,
  leaderEndPoint,
} from './datablock.js';
import { THEME } from './theme.js';

/** Half-width of the charted area, in nautical miles either side of the ARP. */
const HALF_EXTENT_NM = 2.1;

/** Feet in a nautical mile, for turning charted widths into scale. */
const FT_PER_NM = 6076;

/** Narrowest a runway may be drawn. See the note on exaggeration above. */
const MIN_PAVEMENT_PX = 5;

/** Apron names shortened to what fits a panel this narrow. */
const SHORT_APRON = new Map<string, string>([
  ['Terminal 3', 'T3'],
  ['Terminal 1', 'T1'],
  ['Cargo', 'CGO'],
]);

/** Where along a taxiway its designator is printed. */
const TAXIWAY_LABEL_FRACTION = 0.25;

/** Overlap below this is a graze, not a collision worth hiding text for. */
const LABEL_TOUCH_TOLERANCE_PX = 1.5;

/** Cap height of the chart's label fonts, for measuring claim boxes. */
const LABEL_HEIGHT_PX = 10;

/** Taxiways shorter than this on screen go unlabelled. */
const MIN_TAXIWAY_LABEL_PX = 45;

/** Stands closer together than this on screen go unlabelled. */
const MIN_STAND_LABEL_GAP_PX = 16;

/** Aircraft above this height are not on the aerodrome in any useful sense. */
const CHART_CEILING_FT = 3000;

/** Within this height of the surface an aircraft is drawn as being on it. */
const ON_GROUND_FT = 60;

/** Which runways the session is working, so the chart can show them. */
export interface ActiveRunways {
  readonly arrival: string;
  readonly departure: string;
}

interface ScreenPoint {
  x: number;
  y: number;
}

export class GroundChart {
  private readonly ctx: CanvasRenderingContext2D;
  private scale = 1;
  private originX = 0;
  private originY = 0;
  /** Boxes claimed by chart labels this frame, so none print over another. */
  private claimed: Box[] = [];

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
  private toScreen(p: Point): ScreenPoint {
    return { x: this.originX + p.x * this.scale, y: this.originY - p.y * this.scale };
  }

  render(
    aircraft: readonly Aircraft[],
    selectedId: string | null,
    active: ActiveRunways,
  ): void {
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    const ctx = this.ctx;
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.fillStyle = THEME.background;
    ctx.fillRect(0, 0, rect.width, rect.height);
    this.claimed = [];

    // Surfaces back to front, the way they actually lie: apron, then the
    // taxiways crossing it, then the runways over everything.
    this.drawAprons();
    this.drawStands();
    this.drawTaxiways();
    this.drawRunwayPavement(active);

    // Then the lettering, most important first. Each label claims its box and
    // a later one that would collide is dropped, so the order here is a
    // priority order: a runway designator is worth more than a taxiway
    // letter, which is worth more than a terminal name.
    this.drawRunwayLabels(active);
    this.drawTaxiwayLabels();
    this.drawApronLabels();

    this.drawAircraft(aircraft, selectedId);
    this.drawCompass(rect.width);
    this.drawScale(rect.height);
  }

  // ------------------------------------------------------------- surfaces

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
      ctx.fillStyle = THEME.apronFill;
      ctx.fill();
      ctx.strokeStyle = THEME.apronEdge;
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }

  private drawTaxiways(): void {
    const ctx = this.ctx;
    ctx.strokeStyle = THEME.taxiway;
    ctx.lineWidth = 2.2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    for (const taxiway of this.airspace.groundChart.taxiways) {
      if (taxiway.centreline.length < 2) continue;
      ctx.beginPath();
      for (const [i, p] of taxiway.centreline.entries()) {
        const s = this.toScreen(p);
        if (i === 0) ctx.moveTo(s.x, s.y);
        else ctx.lineTo(s.x, s.y);
      }
      ctx.stroke();
    }

  }

  private drawTaxiwayLabels(): void {
    const ctx = this.ctx;
    // Designators a quarter of the way along, which is the one stretch of a
    // parallel taxiway that is clear of everything else. The midpoint is
    // where the runway crosses it, and either end is where the runway's own
    // designator sits — labels there came out as "D28" and "C29L".
    //
    // A taxiway too short to have a clear quarter-point goes unlabelled: the
    // rapid-exit links are twenty pixels long here, so a quarter of the way
    // along is still on the runway. As with the stands, the rule is measured
    // rather than a list of exceptions, so it holds at any panel size.
    ctx.font = THEME.fontSmall;
    for (const taxiway of this.airspace.groundChart.taxiways) {
      if (this.lengthPx(taxiway.centreline) < MIN_TAXIWAY_LABEL_PX) continue;
      const at = this.pointAlong(taxiway.centreline, TAXIWAY_LABEL_FRACTION);
      if (at === null) continue;
      this.labelWithGround(taxiway.ident, at.x, at.y, THEME.taxiwayLabel);
    }
  }

  /** On-screen length of a polyline, in pixels. */
  private lengthPx(line: readonly Point[]): number {
    let total = 0;
    for (let i = 1; i < line.length; i += 1) {
      const a = line[i - 1];
      const b = line[i];
      if (a === undefined || b === undefined) continue;
      total += Math.hypot(a.x - b.x, a.y - b.y);
    }
    return total * this.scale;
  }

  /** A point a given fraction of the way along a polyline, in screen pixels. */
  private pointAlong(line: readonly Point[], fraction: number): ScreenPoint | null {
    if (line.length < 2) return null;
    const points = line.map((p) => this.toScreen(p));

    const spans: number[] = [];
    let total = 0;
    for (let i = 1; i < points.length; i += 1) {
      const a = points[i - 1];
      const b = points[i];
      if (a === undefined || b === undefined) return null;
      const d = Math.hypot(b.x - a.x, b.y - a.y);
      spans.push(d);
      total += d;
    }
    if (total === 0) return points[0] ?? null;

    let travelled = fraction * total;
    for (let i = 0; i < spans.length; i += 1) {
      const span = spans[i] ?? 0;
      if (travelled <= span) {
        const a = points[i];
        const b = points[i + 1];
        if (a === undefined || b === undefined) return null;
        const t = span === 0 ? 0 : travelled / span;
        return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
      }
      travelled -= span;
    }
    return points.at(-1) ?? null;
  }

  /**
   * Runway pavement, thresholds and designators.
   *
   * Each strip of tarmac carries two runways, one at each end, so the
   * pavement is drawn once per pair — painting it twice would double the
   * edge stroke and show through as a heavier outline.
   */
  private drawRunwayPavement(active: ActiveRunways): void {
    const ctx = this.ctx;
    const activeIdents = new Set([active.arrival, active.departure]);
    const painted = new Set<string>();

    for (const runway of this.airspace.runways) {
      const key = pairKey(runway);
      if (painted.has(key)) continue;
      painted.add(key);

      const from = this.toScreen(runway.threshold);
      const to = this.toScreen(runway.stopEnd);
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      const len = Math.hypot(dx, dy) || 1;
      const ux = dx / len;
      const uy = dy / len;
      const nx = -uy;
      const ny = ux;

      const half = Math.max(MIN_PAVEMENT_PX, (runway.widthFt / FT_PER_NM) * this.scale) / 2;
      const lit = activeIdents.has(runway.ident) || activeIdents.has(oppositeOf(runway, this.airspace));

      // The pavement itself.
      ctx.beginPath();
      ctx.moveTo(from.x + nx * half, from.y + ny * half);
      ctx.lineTo(to.x + nx * half, to.y + ny * half);
      ctx.lineTo(to.x - nx * half, to.y - ny * half);
      ctx.lineTo(from.x - nx * half, from.y - ny * half);
      ctx.closePath();
      ctx.fillStyle = lit ? THEME.pavementActive : THEME.pavement;
      ctx.fill();
      ctx.strokeStyle = THEME.pavementEdge;
      ctx.lineWidth = 0.75;
      ctx.stroke();

      // Centreline dashes, the marking that makes a runway read as a runway.
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = THEME.runwayMarking;
      ctx.lineWidth = 0.9;
      ctx.beginPath();
      ctx.moveTo(from.x + ux * 4, from.y + uy * 4);
      ctx.lineTo(to.x - ux * 4, to.y - uy * 4);
      ctx.stroke();
      ctx.restore();

      // A threshold bar across each end.
      ctx.strokeStyle = THEME.runwayMarking;
      ctx.lineWidth = 1.4;
      for (const end of [from, to]) {
        const inset = end === from ? 2 : -2;
        ctx.beginPath();
        ctx.moveTo(end.x + ux * inset + nx * half, end.y + uy * inset + ny * half);
        ctx.lineTo(end.x + ux * inset - nx * half, end.y + uy * inset - ny * half);
        ctx.stroke();
      }
    }

  }

  /** One designator per runway end, the active pair picked out in amber. */
  private drawRunwayLabels(active: ActiveRunways): void {
    const ctx = this.ctx;
    const activeIdents = new Set([active.arrival, active.departure]);

    for (const runway of this.airspace.runways) {
      const from = this.toScreen(runway.threshold);
      const to = this.toScreen(runway.stopEnd);
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      const len = Math.hypot(dx, dy) || 1;

      const x = from.x - (dx / len) * 14;
      const y = from.y - (dy / len) * 14;
      const inUse = activeIdents.has(runway.ident);

      let angle = Math.atan2(dy, dx);
      // Keep the text the right way up rather than upside down.
      if (angle > Math.PI / 2 || angle < -Math.PI / 2) angle += Math.PI;

      // Claim the space the rotated text actually occupies. A square big
      // enough to hold it at any angle over-claims at the corners: it cost
      // 29L its designator, dropped against an 09 label twenty-one pixels
      // away that it never really touched.
      ctx.font = THEME.fontLabel;
      const textW = ctx.measureText(runway.ident).width;
      const cos = Math.abs(Math.cos(angle));
      const sin = Math.abs(Math.sin(angle));
      const halfW = (textW * cos + LABEL_HEIGHT_PX * sin) / 2 + 1;
      const halfH = (textW * sin + LABEL_HEIGHT_PX * cos) / 2 + 1;
      const box: Box = { x: x - halfW, y: y - halfH, w: halfW * 2, h: halfH * 2 };
      if (this.claimed.some((c) => boxesOverlap(box, c))) continue;
      this.claimed.push(box);

      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(angle);
      ctx.font = THEME.fontLabel;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = inUse ? THEME.targetSelected : THEME.runwayLabel;
      ctx.fillText(runway.ident, 0, 0);
      ctx.restore();
    }
  }

  /**
   * Stands, drawn as the short ticks a chart uses rather than dots: a mark
   * pointing off the apron edge reads as a parking position, where a square
   * reads as a piece of dirt.
   */
  private drawStands(): void {
    const ctx = this.ctx;
    ctx.strokeStyle = THEME.standMark;
    ctx.lineWidth = 1.6;
    ctx.lineCap = 'butt';

    for (const stand of this.airspace.groundChart.stands) {
      const s = this.toScreen(stand.position);
      ctx.beginPath();
      ctx.moveTo(s.x, s.y - 2.5);
      ctx.lineTo(s.x, s.y + 2.5);
      ctx.stroke();
    }

    // Stand numbers only when the stands are actually far enough apart to
    // carry them. In a side panel this narrow they are three pixels apart and
    // the labels overlap into a smear, so the rule is measured rather than
    // guessed: if the closest pair cannot fit a label between them, none are
    // drawn and the ticks speak for themselves. Give the panel more room and
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
   * Apron names, drawn after the surfaces.
   *
   * They sit on top of the taxiways rather than under them: at this scale the
   * aprons are crossed by their own link taxiways, and a label half hidden
   * behind a line is worse than one that plainly covers it.
   */
  private drawApronLabels(): void {
    const ctx = this.ctx;
    ctx.font = THEME.fontSmall;

    for (const apron of this.airspace.groundChart.aprons) {
      if (apron.outline.length < 3) continue;
      const cx = apron.outline.reduce((a, p) => a + p.x, 0) / apron.outline.length;
      const cy = apron.outline.reduce((a, p) => a + p.y, 0) / apron.outline.length;
      const c = this.toScreen({ x: cx, y: cy });
      const label = SHORT_APRON.get(apron.ident) ?? apron.ident.toUpperCase();
      this.labelWithGround(label, c.x, c.y, THEME.chartLabel);
    }
  }

  /**
   * Centred text over a slab of ground, so it reads over whatever it covers.
   *
   * Returns false and draws nothing when the space is already taken by
   * another chart label. Dropping the second label is the right call here:
   * these name fixed furniture a controller can find again by looking, unlike
   * an aircraft callsign, which has to be shown somewhere.
   */
  private labelWithGround(text: string, x: number, y: number, colour: string): boolean {
    const ctx = this.ctx;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const width = ctx.measureText(text).width;
    const box: Box = { x: x - width / 2 - 2, y: y - 5, w: width + 4, h: 10 };
    if (this.claimed.some((c) => boxesOverlap(box, c))) return false;
    this.claimed.push(box);

    ctx.fillStyle = THEME.background;
    ctx.fillRect(box.x, box.y, box.w, box.h);
    ctx.fillStyle = colour;
    ctx.fillText(text, x, y);
    return true;
  }

  // ------------------------------------------------------------- traffic

  /**
   * Aircraft on or just above the aerodrome.
   *
   * The filter is height and position: anything above 3,000 ft or outside the
   * charted square is somewhere else, and drawing it here would be a lie
   * about where it is. An aircraft actually on the surface is drawn solid; one
   * still in the air is hollow, so a rollout is not mistaken for an approach.
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

    // Symbols first, so no label is drawn under a later aircraft's chevron.
    for (const ac of onField) {
      const s = this.toScreen(ac.position);
      const colour = ac.id === selectedId ? THEME.targetSelected : THEME.target;
      const grounded = ac.altitudeFt - elevation <= ON_GROUND_FT;

      ctx.save();
      ctx.translate(s.x, s.y);
      ctx.rotate((ac.headingDeg * Math.PI) / 180);
      ctx.beginPath();
      ctx.moveTo(0, -5.5);
      ctx.lineTo(3.6, 4);
      ctx.lineTo(0, 2);
      ctx.lineTo(-3.6, 4);
      ctx.closePath();
      if (grounded) {
        ctx.fillStyle = colour;
        ctx.fill();
      } else {
        ctx.strokeStyle = colour;
        ctx.lineWidth = 1.2;
        ctx.stroke();
      }
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

  // ------------------------------------------------------------ furniture

  /** A north arrow, because a chart without one is a picture. */
  private drawCompass(width: number): void {
    const ctx = this.ctx;
    const x = width - 18;
    const y = 20;

    ctx.strokeStyle = THEME.northArrow;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, y + 9);
    ctx.lineTo(x, y - 9);
    ctx.stroke();

    ctx.fillStyle = THEME.northArrow;
    ctx.beginPath();
    ctx.moveTo(x, y - 12);
    ctx.lineTo(x - 3, y - 5);
    ctx.lineTo(x + 3, y - 5);
    ctx.closePath();
    ctx.fill();

    ctx.font = THEME.fontSmall;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText('N', x, y + 11);
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

/**
 * A key shared by the two runways on one strip of tarmac.
 *
 * Each runway's stop end is the other's threshold, so the midpoint of the
 * pavement is the same for both; rounding it is enough to pair them.
 */
function pairKey(runway: Runway): string {
  const mx = (runway.threshold.x + runway.stopEnd.x) / 2;
  const my = (runway.threshold.y + runway.stopEnd.y) / 2;
  return `${mx.toFixed(3)},${my.toFixed(3)}`;
}

/** The ident at the other end of the same pavement, or the runway's own. */
function oppositeOf(runway: Runway, airspace: Airspace): string {
  const key = pairKey(runway);
  const other = airspace.runways.find((r) => r.ident !== runway.ident && pairKey(r) === key);
  return other?.ident ?? runway.ident;
}

/**
 * Do two label boxes genuinely collide?
 *
 * Bare intersection is too strict for this. Runway 29L's designator sits
 * beside 09's with their claim boxes grazing by three tenths of a pixel, and
 * treating that as a clash cost 29L its label entirely. A collision has to be
 * wide enough to actually be seen before it is worth suppressing text over.
 */
function boxesOverlap(a: Box, b: Box): boolean {
  const overlapX = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const overlapY = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return overlapX > LABEL_TOUCH_TOLERANCE_PX && overlapY > LABEL_TOUCH_TOLERANCE_PX;
}
