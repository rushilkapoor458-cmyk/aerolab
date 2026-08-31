/**
 * Typed view over `src/data/airspace.json`.
 *
 * The JSON is the editable source of truth and stores geography as lat/lon
 * and every course as TRUE degrees. This module validates it, projects every
 * position into the local tangent plane once at load time, and exposes lookup
 * helpers. Nothing downstream touches raw JSON.
 */

import { LatLon, Point, Projection, normalizeDeg, pointInPolygon, trueToMagnetic } from './geo.js';
import { FT_PER_NM } from './units.js';

export type FixType = 'boundary' | 'terminal' | 'enroute' | 'faf';
export type TurnDirection = 'left' | 'right';
export type AltitudeConstraintType = 'at' | 'at_or_above' | 'at_or_below';
export type SpeedConstraintType = 'at' | 'at_or_below';

export interface AltitudeConstraint {
  readonly type: AltitudeConstraintType;
  readonly altitudeFt: number;
}

export interface SpeedConstraint {
  readonly type: SpeedConstraintType;
  readonly speedKt: number;
}

export interface Airport {
  readonly icao: string;
  readonly iata: string;
  readonly name: string;
  readonly city: string;
  readonly elevationFt: number;
  readonly magneticVariationDeg: number;
  readonly referencePoint: LatLon;
  readonly transitionAltitudeFt: number;
  readonly approachFrequencyMhz: number;
  readonly towerFrequencyMhz: number;
}

export interface Runway {
  readonly ident: string;
  /** Centreline course in true degrees, in the landing direction. */
  readonly trueHeadingDeg: number;
  /** Same course expressed magnetically, for display and phraseology. */
  readonly magneticHeadingDeg: number;
  readonly threshold: Point;
  readonly thresholdLatLon: LatLon;
  readonly thresholdElevationFt: number;
  readonly lengthFt: number;
  readonly lengthNm: number;
  readonly widthFt: number;
  /** Localiser frequency, or null where the runway has no ILS. */
  readonly ilsFrequencyMhz: number | null;
  readonly glideslopeAngleDeg: number;
  readonly category: string;
  /** Far end of the paved surface, for drawing. */
  readonly stopEnd: Point;
}

export interface Fix {
  readonly name: string;
  readonly position: Point;
  readonly latLon: LatLon;
  readonly type: FixType;
}

export interface Airway {
  readonly ident: string;
  readonly fixes: readonly string[];
}

export interface ProcedureLeg {
  readonly fix: string;
  readonly altitudeConstraint: AltitudeConstraint | null;
  readonly speedConstraint: SpeedConstraint | null;
}

export interface Sid {
  readonly ident: string;
  readonly runways: readonly string[];
  readonly legs: readonly ProcedureLeg[];
}

export interface Star {
  readonly ident: string;
  readonly boundaryFix: string;
  readonly legs: readonly ProcedureLeg[];
}

export interface Approach {
  readonly ident: string;
  readonly runway: string;
  readonly type: string;
  readonly localiserCourseTrueDeg: number;
  readonly localiserCourseMagneticDeg: number;
  readonly finalApproachFix: string;
  readonly fafAltitudeFt: number;
  readonly interceptAltitudeFt: number;
  readonly interceptRangeNm: number;
  readonly maxInterceptAngleDeg: number;
  readonly glideslopeAngleDeg: number;
  readonly decisionHeightFt: number;
  readonly missedApproachAltitudeFt: number;
}

export interface Hold {
  readonly fix: string;
  readonly inboundCourseTrueDeg: number;
  readonly turnDirection: TurnDirection;
  readonly legTimeSec: number;
  readonly maxSpeedKt: number;
  readonly minAltitudeFt: number;
  readonly maxAltitudeFt: number;
}

export interface Sector {
  readonly name: string;
  readonly radiusNm: number;
  readonly floorFt: number;
  readonly ceilingFt: number;
  readonly boundary: readonly Point[];
}

export interface MsaGrid {
  readonly origin: Point;
  readonly cellSizeNm: number;
  readonly rows: number;
  readonly cols: number;
  readonly values: readonly (readonly number[])[];
}

/**
 * The aerodrome layout, for the ground chart.
 *
 * Runway positions and dimensions are real; the taxiway, apron and stand
 * geometry is a plausible schematic derived from them rather than the
 * published VIDP chart, and is flagged as approximated in the data.
 */
export interface Taxiway {
  readonly ident: string;
  readonly centreline: readonly Point[];
}

export interface Apron {
  readonly ident: string;
  readonly outline: readonly Point[];
}

export interface Stand {
  readonly ident: string;
  readonly position: Point;
  readonly apron: string;
}

export interface GroundChart {
  readonly approximated: boolean;
  readonly note: string;
  readonly taxiways: readonly Taxiway[];
  readonly aprons: readonly Apron[];
  readonly stands: readonly Stand[];
}

export class Airspace {
  readonly projection: Projection;
  readonly airport: Airport;
  readonly sector: Sector;
  readonly runways: readonly Runway[];
  readonly fixes: readonly Fix[];
  readonly airways: readonly Airway[];
  readonly sids: readonly Sid[];
  readonly stars: readonly Star[];
  readonly approaches: readonly Approach[];
  readonly holds: readonly Hold[];
  readonly msaGrid: MsaGrid;
  readonly groundChart: GroundChart;

  private readonly fixIndex: ReadonlyMap<string, Fix>;
  private readonly runwayIndex: ReadonlyMap<string, Runway>;
  private readonly approachIndex: ReadonlyMap<string, Approach>;

  constructor(raw: RawAirspace) {
    const airport = raw.airport;
    this.projection = new Projection(airport.referencePoint);
    const variation = airport.magneticVariationDeg;

    this.airport = { ...airport };

    this.sector = {
      name: raw.sector.name,
      radiusNm: raw.sector.radiusNm,
      floorFt: raw.sector.floorFt,
      ceilingFt: raw.sector.ceilingFt,
      boundary: raw.sector.boundary.map((ll) => this.projection.toLocal(ll)),
    };

    this.runways = raw.runways.map((r) => {
      const threshold = this.projection.toLocal(r.threshold);
      const lengthNm = r.lengthFt / FT_PER_NM;
      const course = normalizeDeg(r.trueHeadingDeg);
      return {
        ident: r.ident,
        trueHeadingDeg: course,
        magneticHeadingDeg: trueToMagnetic(course, variation),
        threshold,
        thresholdLatLon: r.threshold,
        thresholdElevationFt: r.thresholdElevationFt,
        lengthFt: r.lengthFt,
        lengthNm,
        widthFt: r.widthFt,
        ilsFrequencyMhz: r.ilsFrequencyMhz,
        glideslopeAngleDeg: r.glideslopeAngleDeg,
        category: r.category,
        stopEnd: {
          x: threshold.x + Math.sin((course * Math.PI) / 180) * lengthNm,
          y: threshold.y + Math.cos((course * Math.PI) / 180) * lengthNm,
        },
      };
    });

    this.fixes = raw.fixes.map((f) => ({
      name: f.name,
      position: this.projection.toLocal({ lat: f.lat, lon: f.lon }),
      latLon: { lat: f.lat, lon: f.lon },
      type: f.type,
    }));

    this.airways = raw.airways.map((a) => ({ ident: a.ident, fixes: [...a.fixes] }));
    this.sids = raw.sids.map((s) => ({ ident: s.ident, runways: [...s.runways], legs: [...s.legs] }));
    this.stars = raw.stars.map((s) => ({
      ident: s.ident,
      boundaryFix: s.boundaryFix,
      legs: [...s.legs],
    }));

    this.approaches = raw.approaches.map((a) => ({
      ...a,
      localiserCourseMagneticDeg: trueToMagnetic(a.localiserCourseTrueDeg, variation),
    }));

    this.holds = raw.holds.map((h) => ({ ...h }));

    const ground = raw.groundChart;
    this.groundChart = {
      approximated: ground.approximated,
      note: ground.note,
      taxiways: ground.taxiways.map((w) => ({
        ident: w.ident,
        centreline: w.centreline.map((ll) => this.projection.toLocal(ll)),
      })),
      aprons: ground.aprons.map((a) => ({
        ident: a.ident,
        outline: a.outline.map((ll) => this.projection.toLocal(ll)),
      })),
      stands: ground.stands.map((s) => ({
        ident: s.ident,
        position: this.projection.toLocal(s.position),
        apron: s.apron,
      })),
    };

    this.msaGrid = {
      origin: this.projection.toLocal({ lat: raw.msaGrid.originLat, lon: raw.msaGrid.originLon }),
      cellSizeNm: raw.msaGrid.cellSizeNm,
      rows: raw.msaGrid.rows,
      cols: raw.msaGrid.cols,
      values: raw.msaGrid.minimumSafeAltitudeFt,
    };

    this.fixIndex = new Map(this.fixes.map((f) => [f.name, f]));
    this.runwayIndex = new Map(this.runways.map((r) => [r.ident, r]));
    this.approachIndex = new Map(this.approaches.map((a) => [a.runway, a]));

    this.validate();
  }

  /** Every fix, runway and approach a procedure names must actually exist. */
  private validate(): void {
    const problems: string[] = [];
    const checkFix = (name: string, where: string): void => {
      if (!this.fixIndex.has(name)) problems.push(`${where} references unknown fix ${name}`);
    };
    for (const airway of this.airways) {
      for (const f of airway.fixes) checkFix(f, `airway ${airway.ident}`);
    }
    for (const sid of this.sids) {
      for (const leg of sid.legs) checkFix(leg.fix, `SID ${sid.ident}`);
      for (const r of sid.runways) {
        if (!this.runwayIndex.has(r)) problems.push(`SID ${sid.ident} references unknown runway ${r}`);
      }
    }
    for (const star of this.stars) {
      for (const leg of star.legs) checkFix(leg.fix, `STAR ${star.ident}`);
      checkFix(star.boundaryFix, `STAR ${star.ident} boundary fix`);
    }
    for (const app of this.approaches) {
      checkFix(app.finalApproachFix, `approach ${app.ident}`);
      const runway = this.runwayIndex.get(app.runway);
      if (runway === undefined) {
        problems.push(`approach ${app.ident} references unknown runway ${app.runway}`);
      } else if (runway.ilsFrequencyMhz === null) {
        problems.push(`approach ${app.ident} is published for runway ${app.runway}, which has no ILS`);
      }
    }
    for (const hold of this.holds) checkFix(hold.fix, `hold at ${hold.fix}`);
    // A sector entry fix outside its own sector means traffic arrives already
    // out of the airspace, which the safety net would rightly complain about.
    for (const fix of this.fixes) {
      if (fix.type !== 'boundary') continue;
      if (!pointInPolygon(fix.position, this.sector.boundary)) {
        problems.push(`boundary fix ${fix.name} lies outside the sector boundary`);
      }
    }
    if (this.msaGrid.values.length !== this.msaGrid.rows) {
      problems.push(`MSA grid declares ${this.msaGrid.rows} rows but holds ${this.msaGrid.values.length}`);
    }
    if (problems.length > 0) {
      throw new Error(`airspace.json is inconsistent:\n  - ${problems.join('\n  - ')}`);
    }
  }

  fix(name: string): Fix | undefined {
    return this.fixIndex.get(name.toUpperCase());
  }

  runway(ident: string): Runway | undefined {
    return this.runwayIndex.get(ident.toUpperCase());
  }

  approachForRunway(ident: string): Approach | undefined {
    return this.approachIndex.get(ident.toUpperCase());
  }

  star(ident: string): Star | undefined {
    const wanted = ident.toUpperCase();
    return this.stars.find((s) => s.ident === wanted);
  }

  sid(ident: string): Sid | undefined {
    const wanted = ident.toUpperCase();
    return this.sids.find((s) => s.ident === wanted);
  }

  /** The leg of a named SID or STAR that crosses a given fix. */
  procedureLeg(procedureIdent: string, fixName: string): ProcedureLeg | undefined {
    const procedure = this.star(procedureIdent) ?? this.sid(procedureIdent);
    if (procedure === undefined) return undefined;
    const wanted = fixName.toUpperCase();
    return procedure.legs.find((leg) => leg.fix.toUpperCase() === wanted);
  }

  hold(fixName: string): Hold | undefined {
    return this.holds.find((h) => h.fix === fixName.toUpperCase());
  }

  /**
   * Minimum safe altitude at a point, in feet AMSL, or null where the grid
   * publishes nothing. Null means "no terrain data here", not "no terrain":
   * callers must not invent a figure, and must not alert on one either.
   */
  minimumSafeAltitudeFt(p: Point): number | null {
    const col = Math.floor((p.x - this.msaGrid.origin.x) / this.msaGrid.cellSizeNm);
    const row = Math.floor((p.y - this.msaGrid.origin.y) / this.msaGrid.cellSizeNm);
    const line = this.msaGrid.values[row];
    return line?.[col] ?? null;
  }

  /** True bearing to magnetic, using this airport's variation. */
  toMagnetic(trueDeg: number): number {
    return trueToMagnetic(trueDeg, this.airport.magneticVariationDeg);
  }

  /** Magnetic bearing to true, using this airport's variation. */
  toTrue(magneticDeg: number): number {
    return normalizeDeg(magneticDeg + this.airport.magneticVariationDeg);
  }
}

/* ------------------------------------------------------------------ */
/* Shapes of the raw JSON. Kept separate from the runtime types above  */
/* so that swapping in another airport's file fails loudly at load.    */
/* ------------------------------------------------------------------ */

interface RawRunway {
  ident: string;
  trueHeadingDeg: number;
  threshold: LatLon;
  thresholdElevationFt: number;
  lengthFt: number;
  widthFt: number;
  ilsFrequencyMhz: number | null;
  glideslopeAngleDeg: number;
  category: string;
}

interface RawFix {
  name: string;
  lat: number;
  lon: number;
  type: FixType;
}

export interface RawAirspace {
  schemaVersion: number;
  airport: Airport;
  sector: {
    name: string;
    radiusNm: number;
    floorFt: number;
    ceilingFt: number;
    boundary: LatLon[];
  };
  runways: RawRunway[];
  fixes: RawFix[];
  airways: { ident: string; fixes: string[] }[];
  sids: { ident: string; runways: string[]; legs: ProcedureLeg[] }[];
  stars: { ident: string; boundaryFix: string; legs: ProcedureLeg[] }[];
  approaches: Omit<Approach, 'localiserCourseMagneticDeg'>[];
  holds: Hold[];
  groundChart: {
    approximated: boolean;
    note: string;
    taxiways: { ident: string; centreline: LatLon[] }[];
    aprons: { ident: string; outline: LatLon[] }[];
    stands: { ident: string; position: LatLon; apron: string }[];
  };
  msaGrid: {
    originLat: number;
    originLon: number;
    cellSizeNm: number;
    rows: number;
    cols: number;
    minimumSafeAltitudeFt: number[][];
  };
}
