import { describe, expect, it } from 'vitest';
import airspaceData from '../data/airspace.json';
import { Airspace, RawAirspace } from './airspace.js';
import {
  THRESHOLD_CROSSING_HEIGHT_FT,
  approachSpeedKt,
  canCaptureGlideslope,
  canCaptureLocaliser,
  checkStability,
  glideslopeVerticalSpeedFpm,
  localiserGeometry,
  localiserHalfWidthNm,
  localiserTrackTrueDeg,
} from './approach.js';
import { angleDiff, movePoint } from './geo.js';
import { makeTestAircraft } from './testAircraft.js';
import { Aircraft } from './types.js';

const AIRSPACE = new Airspace(airspaceData as unknown as RawAirspace);
const RUNWAY_29 = AIRSPACE.runway('29');
const APPROACH_29 = AIRSPACE.approachForRunway('29');
if (RUNWAY_29 === undefined || APPROACH_29 === undefined) throw new Error('runway 29 missing');
const RUNWAY = RUNWAY_29;
const APPROACH = APPROACH_29;

interface Placement {
  /** Distance from the threshold along the localiser, NM. */
  readonly distanceNm: number;
  /** Displacement from the centreline, NM. Positive is right of course. */
  readonly offsetNm?: number;
  readonly altitudeFt: number;
  /** Ground track. Defaults to the localiser course. */
  readonly trackDeg?: number;
  readonly iasKt?: number;
}

function place(p: Placement, type = 'A320'): Aircraft {
  const reciprocal = (RUNWAY.trueHeadingDeg + 180) % 360;
  const onCentreline = movePoint(RUNWAY.threshold, reciprocal, p.distanceNm);
  const right = (RUNWAY.trueHeadingDeg + 90) % 360;
  const position = movePoint(onCentreline, right, p.offsetNm ?? 0);
  const track = p.trackDeg ?? RUNWAY.trueHeadingDeg;
  const speed = p.iasKt ?? 180;
  return makeTestAircraft(
    {
      position,
      altitudeFt: p.altitudeFt,
      headingDeg: track,
      trueTrackDeg: track,
      iasKt: speed,
      groundspeedKt: speed,
      clearance: { headingDeg: track, altitudeFt: p.altitudeFt, speedKt: speed },
      approach: {
        runway: '29',
        ident: 'ILS29',
        localiserCaptured: false,
        glideslopeCaptured: false,
        reportedBlowThrough: false,
        stabilityChecked: false,
      },
    },
    type,
  );
}

describe('localiser geometry', () => {
  it('measures distance along the centreline', () => {
    const geo = localiserGeometry(place({ distanceNm: 8, altitudeFt: 2600 }), RUNWAY, APPROACH);
    expect(geo.distanceToThresholdNm).toBeCloseTo(8, 6);
    expect(geo.crossTrackNm).toBeCloseTo(0, 6);
  });

  it('signs the displacement: positive to the right of the course', () => {
    const right = localiserGeometry(place({ distanceNm: 8, offsetNm: 2, altitudeFt: 3000 }), RUNWAY, APPROACH);
    const left = localiserGeometry(place({ distanceNm: 8, offsetNm: -2, altitudeFt: 3000 }), RUNWAY, APPROACH);
    expect(right.crossTrackNm).toBeCloseTo(2, 6);
    expect(left.crossTrackNm).toBeCloseTo(-2, 6);
  });

  it('puts the glidepath at three degrees above the threshold', () => {
    const geo = localiserGeometry(place({ distanceNm: 10, altitudeFt: 3000 }), RUNWAY, APPROACH);
    // Three degrees is very nearly 318 feet per nautical mile.
    const expected = RUNWAY.thresholdElevationFt + THRESHOLD_CROSSING_HEIGHT_FT + 10 * 318.4;
    expect(geo.glideslopeAltitudeFt).toBeCloseTo(expected, 0);
  });

  it('reports the aircraft above or below the path', () => {
    const high = localiserGeometry(place({ distanceNm: 6, altitudeFt: 4000 }), RUNWAY, APPROACH);
    const low = localiserGeometry(place({ distanceNm: 6, altitudeFt: 2000 }), RUNWAY, APPROACH);
    expect(high.aboveGlideslopeFt).toBeGreaterThan(0);
    expect(low.aboveGlideslopeFt).toBeLessThan(0);
  });
});

describe('localiser capture', () => {
  it('captures a good intercept', () => {
    const ac = place({ distanceNm: 12, offsetNm: 0.2, altitudeFt: 3000, trackDeg: RUNWAY.trueHeadingDeg - 25 });
    expect(canCaptureLocaliser(localiserGeometry(ac, RUNWAY, APPROACH), APPROACH)).toBe(true);
  });

  it('refuses an intercept steeper than thirty degrees', () => {
    const ac = place({ distanceNm: 12, offsetNm: 0.1, altitudeFt: 3000, trackDeg: RUNWAY.trueHeadingDeg - 70 });
    expect(canCaptureLocaliser(localiserGeometry(ac, RUNWAY, APPROACH), APPROACH)).toBe(false);
  });

  it('refuses a capture outside the beam', () => {
    const ac = place({ distanceNm: 12, offsetNm: 3, altitudeFt: 3000 });
    expect(canCaptureLocaliser(localiserGeometry(ac, RUNWAY, APPROACH), APPROACH)).toBe(false);
  });

  it('refuses a capture beyond the published intercept range', () => {
    const ac = place({ distanceNm: APPROACH.interceptRangeNm + 5, altitudeFt: 5000 });
    expect(canCaptureLocaliser(localiserGeometry(ac, RUNWAY, APPROACH), APPROACH)).toBe(false);
  });

  it('refuses a capture past the threshold', () => {
    const ac = place({ distanceNm: -1, altitudeFt: 800 });
    expect(canCaptureLocaliser(localiserGeometry(ac, RUNWAY, APPROACH), APPROACH)).toBe(false);
  });

  it('has a beam that narrows towards the runway', () => {
    expect(localiserHalfWidthNm(16)).toBeGreaterThan(localiserHalfWidthNm(4));
    expect(localiserHalfWidthNm(0)).toBeGreaterThan(0);
  });
});

describe('tracking the centreline', () => {
  it('turns towards the course when displaced right of it', () => {
    const geo = localiserGeometry(place({ distanceNm: 8, offsetNm: 0.4, altitudeFt: 2600 }), RUNWAY, APPROACH);
    const track = localiserTrackTrueDeg(geo, RUNWAY.trueHeadingDeg);
    expect(angleDiff(RUNWAY.trueHeadingDeg, track)).toBeLessThan(0);
  });

  it('flies the course exactly when it is on it', () => {
    const geo = localiserGeometry(place({ distanceNm: 8, altitudeFt: 2600 }), RUNWAY, APPROACH);
    expect(localiserTrackTrueDeg(geo, RUNWAY.trueHeadingDeg)).toBeCloseTo(RUNWAY.trueHeadingDeg, 6);
  });

  it('never commands more than a 25 degree correction', () => {
    const geo = localiserGeometry(place({ distanceNm: 8, offsetNm: 5, altitudeFt: 2600 }), RUNWAY, APPROACH);
    const track = localiserTrackTrueDeg(geo, RUNWAY.trueHeadingDeg);
    expect(Math.abs(angleDiff(RUNWAY.trueHeadingDeg, track))).toBeLessThanOrEqual(25.001);
  });
});

describe('glideslope capture', () => {
  it('needs the localiser first', () => {
    const geo = localiserGeometry(place({ distanceNm: 8, altitudeFt: 2600 }), RUNWAY, APPROACH);
    expect(canCaptureGlideslope(geo, false)).toBe(false);
  });

  it('captures from below as the path comes down to the aircraft', () => {
    // At 8 NM the path is near 3370 ft, well above an aircraft level at 3000.
    const under = localiserGeometry(place({ distanceNm: 8, altitudeFt: 3000 }), RUNWAY, APPROACH);
    expect(under.aboveGlideslopeFt).toBeLessThan(-330);
    expect(canCaptureGlideslope(under, true)).toBe(false);

    // By 7 NM the path has come down to it and the capture happens.
    const arriving = localiserGeometry(place({ distanceNm: 7, altitudeFt: 3000 }), RUNWAY, APPROACH);
    expect(canCaptureGlideslope(arriving, true)).toBe(true);
  });

  it('never captures from above', () => {
    const high = localiserGeometry(place({ distanceNm: 6, altitudeFt: 6000 }), RUNWAY, APPROACH);
    expect(high.aboveGlideslopeFt).toBeGreaterThan(0);
    expect(canCaptureGlideslope(high, true)).toBe(false);
  });
});

describe('flying the glideslope', () => {
  it('descends at roughly five times the groundspeed', () => {
    const geo = localiserGeometry(place({ distanceNm: 6, altitudeFt: 0 }), RUNWAY, APPROACH);
    const onPath = { ...geo, aboveGlideslopeFt: 0 };
    const vs = glideslopeVerticalSpeedFpm(onPath, 140, 3);
    expect(vs).toBeLessThan(0);
    expect(Math.abs(vs)).toBeGreaterThan(650);
    expect(Math.abs(vs)).toBeLessThan(820);
  });

  it('eases the descent when below the path and steepens it when above', () => {
    const geo = localiserGeometry(place({ distanceNm: 6, altitudeFt: 0 }), RUNWAY, APPROACH);
    const below = glideslopeVerticalSpeedFpm({ ...geo, aboveGlideslopeFt: -100 }, 140, 3);
    const above = glideslopeVerticalSpeedFpm({ ...geo, aboveGlideslopeFt: 100 }, 140, 3);
    expect(below).toBeGreaterThan(above);
  });
});

describe('approach speed', () => {
  it('backs off in stages towards the final approach speed', () => {
    const ac = place({ distanceNm: 12, altitudeFt: 3000, iasKt: 250 });
    expect(approachSpeedKt(ac, 12)).toBeGreaterThan(approachSpeedKt(ac, 7));
    expect(approachSpeedKt(ac, 7)).toBeGreaterThan(approachSpeedKt(ac, 3));
    expect(approachSpeedKt(ac, 3)).toBe(ac.profile.speeds.approachIasKt);
  });
});

describe('the stability gate', () => {
  const stable = (): Aircraft => {
    const ac = place({ distanceNm: 3, altitudeFt: 1750, iasKt: 145 });
    if (ac.approach !== null) {
      ac.approach.localiserCaptured = true;
      ac.approach.glideslopeCaptured = true;
    }
    return ac;
  };

  it('passes an aircraft on profile', () => {
    const ac = stable();
    const geo = localiserGeometry(ac, RUNWAY, APPROACH);
    expect(checkStability(ac, geo, false).stable).toBe(true);
  });

  it('fails an occupied runway before anything else', () => {
    const ac = stable();
    const geo = localiserGeometry(ac, RUNWAY, APPROACH);
    expect(checkStability(ac, geo, true)).toEqual({
      stable: false,
      reason: 'the runway is still occupied',
    });
  });

  it('fails an aircraft that never got the localiser', () => {
    const ac = stable();
    if (ac.approach !== null) ac.approach.localiserCaptured = false;
    const geo = localiserGeometry(ac, RUNWAY, APPROACH);
    expect(checkStability(ac, geo, false).reason).toMatch(/never got the localiser/);
  });

  it('fails an aircraft off the centreline', () => {
    const ac = place({ distanceNm: 3, offsetNm: 1, altitudeFt: 1750, iasKt: 145 });
    if (ac.approach !== null) {
      ac.approach.localiserCaptured = true;
      ac.approach.glideslopeCaptured = true;
    }
    const geo = localiserGeometry(ac, RUNWAY, APPROACH);
    expect(checkStability(ac, geo, false).reason).toMatch(/not lined up/);
  });

  it('fails an aircraft high on the slope', () => {
    const ac = place({ distanceNm: 3, altitudeFt: 2600, iasKt: 145 });
    if (ac.approach !== null) {
      ac.approach.localiserCaptured = true;
      ac.approach.glideslopeCaptured = true;
    }
    const geo = localiserGeometry(ac, RUNWAY, APPROACH);
    expect(checkStability(ac, geo, false).reason).toMatch(/high on the slope/);
  });

  it('fails an aircraft that is too fast', () => {
    const ac = stable();
    ac.iasKt = 220;
    const geo = localiserGeometry(ac, RUNWAY, APPROACH);
    expect(checkStability(ac, geo, false).reason).toMatch(/too fast/);
  });
});
