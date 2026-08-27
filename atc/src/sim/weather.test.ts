import { describe, expect, it } from 'vitest';
import { defaultWeather, formatMetar, windAtAltitude } from './weather.js';

const FIELD_ELEVATION_FT = 777;

describe('wind aloft', () => {
  it('gives the surface wind at the surface', () => {
    const w = defaultWeather();
    const wind = windAtAltitude(w, FIELD_ELEVATION_FT, FIELD_ELEVATION_FT);
    expect(wind.directionDeg).toBeCloseTo(w.windDirectionDeg, 6);
    expect(wind.speedKt).toBeCloseTo(w.windSpeedKt, 6);
  });

  it('gives the wind aloft at the reference altitude and above it', () => {
    const w = defaultWeather();
    const at = windAtAltitude(w, w.windAloftAltitudeFt, FIELD_ELEVATION_FT);
    expect(at.speedKt).toBeCloseTo(w.windAloftSpeedKt, 6);
    const above = windAtAltitude(w, 30000, FIELD_ELEVATION_FT);
    expect(above.speedKt).toBeCloseTo(w.windAloftSpeedKt, 6);
  });

  it('interpolates in between, strengthening with height', () => {
    const w = defaultWeather();
    const low = windAtAltitude(w, 3000, FIELD_ELEVATION_FT);
    const mid = windAtAltitude(w, 8000, FIELD_ELEVATION_FT);
    expect(low.speedKt).toBeGreaterThan(w.windSpeedKt);
    expect(mid.speedKt).toBeGreaterThan(low.speedKt);
    expect(mid.speedKt).toBeLessThan(w.windAloftSpeedKt);
  });

  it('turns the short way round when the wind backs through north', () => {
    const w = { ...defaultWeather(), windDirectionDeg: 350, windAloftDirectionDeg: 20 };
    const justAbove = windAtAltitude(w, FIELD_ELEVATION_FT + 500, FIELD_ELEVATION_FT);
    expect(justAbove.directionDeg).toBeGreaterThan(349);
    const halfway = windAtAltitude(
      w,
      FIELD_ELEVATION_FT + (w.windAloftAltitudeFt - FIELD_ELEVATION_FT) / 2,
      FIELD_ELEVATION_FT,
    );
    expect(halfway.directionDeg).toBeCloseTo(5, 6);
  });

  it('never reports a direction outside 0 to 360', () => {
    const w = { ...defaultWeather(), windDirectionDeg: 10, windAloftDirectionDeg: 340 };
    for (let alt = 0; alt <= 16000; alt += 500) {
      const wind = windAtAltitude(w, alt, FIELD_ELEVATION_FT);
      expect(wind.directionDeg).toBeGreaterThanOrEqual(0);
      expect(wind.directionDeg).toBeLessThan(360);
    }
  });
});

describe('METAR', () => {
  it('renders the wind, visibility, cloud, temperature and pressure', () => {
    const w = defaultWeather();
    const metar = formatMetar('VIDP', 10 * 3600 + 12 * 60, w);
    expect(metar).toMatch(/^VIDP 121012Z 29012KT 6000 SCT035 31\/18 Q1011$/);
  });

  it('shows a gust when there is one', () => {
    const w = { ...defaultWeather(), windGustKt: 28 };
    expect(formatMetar('VIDP', 0, w)).toMatch(/29012G28KT/);
  });

  it('renders calm and a negative temperature properly', () => {
    const w = { ...defaultWeather(), windSpeedKt: 0, temperatureC: -2, dewpointC: -8 };
    const metar = formatMetar('VIDP', 0, w);
    expect(metar).toMatch(/00000KT/);
    expect(metar).toMatch(/M02\/M08/);
  });

  it('caps visibility at 9999 the way a real report does', () => {
    const w = { ...defaultWeather(), visibilityM: 12000 };
    expect(formatMetar('VIDP', 0, w)).toMatch(/ 9999 /);
  });
});
