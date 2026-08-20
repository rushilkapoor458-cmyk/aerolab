/**
 * Weather state and the METAR/ATIS text derived from it.
 *
 * Milestone 1 holds the weather constant; the debug panel can still change
 * it live, and the wind genuinely drives the wind triangle in `flight.ts`.
 */

import { formatBearing } from './geo.js';
import { pad2 } from './units.js';

export interface Weather {
  /** Direction the wind blows FROM, in magnetic degrees. */
  windDirectionDeg: number;
  windSpeedKt: number;
  windGustKt: number | null;
  visibilityM: number;
  cloudBaseFt: number;
  cloudCover: 'SKC' | 'FEW' | 'SCT' | 'BKN' | 'OVC';
  qnhHpa: number;
  temperatureC: number;
  dewpointC: number;
  /** ATIS identification letter. */
  atisLetter: string;
}

export function defaultWeather(): Weather {
  return {
    windDirectionDeg: 290,
    windSpeedKt: 12,
    windGustKt: null,
    visibilityM: 6000,
    cloudBaseFt: 3500,
    cloudCover: 'SCT',
    qnhHpa: 1011,
    temperatureC: 31,
    dewpointC: 18,
    atisLetter: 'C',
  };
}

/** Render the weather as a METAR string for the ATIS panel. */
export function formatMetar(icao: string, timeSec: number, w: Weather): string {
  const t = ((timeSec % 86400) + 86400) % 86400;
  const day = 12; // The simulation does not model a calendar; the day is fixed.
  const stamp = `${pad2(day)}${pad2(Math.floor(t / 3600))}${pad2(Math.floor((t % 3600) / 60))}Z`;
  const gust = w.windGustKt === null ? '' : `G${pad2(Math.round(w.windGustKt))}`;
  const wind =
    w.windSpeedKt < 1
      ? '00000KT'
      : `${formatBearing(w.windDirectionDeg)}${pad2(Math.round(w.windSpeedKt))}${gust}KT`;
  const vis = w.visibilityM >= 9999 ? '9999' : String(Math.round(w.visibilityM)).padStart(4, '0');
  const cloud =
    w.cloudCover === 'SKC' ? 'SKC' : `${w.cloudCover}${String(Math.round(w.cloudBaseFt / 100)).padStart(3, '0')}`;
  const temp = `${formatTemp(w.temperatureC)}/${formatTemp(w.dewpointC)}`;
  return `${icao} ${stamp} ${wind} ${vis} ${cloud} ${temp} Q${Math.round(w.qnhHpa)}`;
}

function formatTemp(c: number): string {
  const v = Math.round(c);
  return v < 0 ? `M${pad2(Math.abs(v))}` : pad2(v);
}
