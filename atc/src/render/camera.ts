/**
 * Maps the simulation's local NM plane onto canvas pixels.
 *
 * Screen y grows downwards, world y grows north, so the vertical axis flips.
 */

import { Point } from '../sim/geo.js';

export interface ScreenPoint {
  readonly x: number;
  readonly y: number;
}

export const MIN_PX_PER_NM = 2;
export const MAX_PX_PER_NM = 60;

export class Camera {
  /** World point at the centre of the viewport. */
  centre: Point = { x: 0, y: 0 };
  pxPerNm = 8;
  widthPx = 0;
  heightPx = 0;

  resize(widthPx: number, heightPx: number): void {
    this.widthPx = widthPx;
    this.heightPx = heightPx;
  }

  toScreen(p: Point): ScreenPoint {
    return {
      x: this.widthPx / 2 + (p.x - this.centre.x) * this.pxPerNm,
      y: this.heightPx / 2 - (p.y - this.centre.y) * this.pxPerNm,
    };
  }

  toWorld(s: ScreenPoint): Point {
    return {
      x: this.centre.x + (s.x - this.widthPx / 2) / this.pxPerNm,
      y: this.centre.y - (s.y - this.heightPx / 2) / this.pxPerNm,
    };
  }

  /** Pan by a pixel delta, as produced by a mouse drag. */
  panByPixels(dxPx: number, dyPx: number): void {
    this.centre = {
      x: this.centre.x - dxPx / this.pxPerNm,
      y: this.centre.y + dyPx / this.pxPerNm,
    };
  }

  /** Zoom about a screen point, keeping the world point under it fixed. */
  zoomAt(anchor: ScreenPoint, factor: number): void {
    const before = this.toWorld(anchor);
    this.pxPerNm = Math.min(MAX_PX_PER_NM, Math.max(MIN_PX_PER_NM, this.pxPerNm * factor));
    const after = this.toWorld(anchor);
    this.centre = {
      x: this.centre.x + (before.x - after.x),
      y: this.centre.y + (before.y - after.y),
    };
  }

  /** Fit a radius in nautical miles into the smaller viewport dimension. */
  fitRadius(radiusNm: number): void {
    const smaller = Math.min(this.widthPx, this.heightPx);
    if (smaller <= 0 || radiusNm <= 0) return;
    this.pxPerNm = Math.min(MAX_PX_PER_NM, Math.max(MIN_PX_PER_NM, smaller / 2 / radiusNm));
  }
}
