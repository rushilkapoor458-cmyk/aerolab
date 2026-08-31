/**
 * Scope palette and type.
 *
 * A modern European air traffic management console: a deep navy ground, the
 * map drawn in cool blue-greys, traffic and data blocks in near-white, and
 * saturated blue reserved for the aerodrome and the procedure you are
 * working. Amber marks a caution, red a warning.
 *
 * The discipline is that nothing routine is coloured. Blue carries meaning —
 * it says "this is the approach, this is the field" — and if something on
 * this display is amber or red, it wants you.
 *
 * Contrast against the ground was the constraint the greys were chosen for:
 * map furniture sits far enough above the navy to be readable in a dim room
 * without competing with traffic, which is the brightest thing on the scope.
 */

export const THEME = {
  /* ground and map */
  background: '#0a1020',
  rangeRing: '#1a2340',
  rangeRingMajor: '#26325a',
  rangeRingLabel: '#556688',
  compassTick: '#212c4e',
  compassTickMajor: '#374676',
  compassLabel: '#616f9c',
  boundary: '#44548c',
  boundaryGlow: 'rgba(68, 84, 140, 0.24)',

  /* aerodrome and procedures */
  runway: '#eaf0ff',
  runwayLabel: '#98a6cc',
  aerodrome: '#5b8cff',
  centreline: '#2c3a68',
  centrelineTick: '#405084',
  ilsCone: 'rgba(45, 76, 152, 0.26)',
  ilsEdge: '#33529c',
  fafMark: '#5b8cff',
  chartLabel: '#7d8bb8',

  /* navigation */
  fix: '#4a5680',
  fixLabel: '#7886ae',
  fixBoundary: '#6f7fac',
  route: '#8f7fe0',
  approachPath: '#5b8cff',

  /* traffic */
  target: '#eaf0ff',
  targetGlow: 'rgba(234, 240, 255, 0.35)',
  targetSelected: '#ffc44d',
  history: '#6b7699',
  vector: '#aab6da',
  leader: '#5b6690',

  /* data blocks */
  dataBlock: '#eaf0ff',
  dataBlockSelected: '#ffc44d',
  dataBlockCaution: '#ffb020',
  dataBlockAlert: '#ff5f56',
  dataBlockDim: '#69739a',

  /* tools */
  ruler: '#ffc44d',
  scaleBar: '#616f9c',

  /* type */
  fontBlock: '11.5px "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace',
  fontLabel: '10px "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace',
  fontSmall: '9.5px "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace',
} as const;
