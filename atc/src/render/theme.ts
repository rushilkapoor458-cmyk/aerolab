/**
 * Scope palette and type.
 *
 * A modern air traffic management console: a near-black ground, the map in
 * dark neutral greys, traffic and data blocks in white and pale grey, and
 * colour used only where it carries meaning — cyan for the aerodrome and the
 * procedure you are working, amber for a caution, red for a warning.
 *
 * The discipline is that nothing routine is coloured. If something on this
 * display is amber or red, it wants you.
 */

export const THEME = {
  /* ground and map */
  background: '#0b0d10',
  rangeRing: '#1b2027',
  rangeRingMajor: '#272e37',
  rangeRingLabel: '#4d5763',
  compassTick: '#232a33',
  compassTickMajor: '#39424e',
  compassLabel: '#5a6473',
  boundary: '#3d4753',
  boundaryGlow: 'rgba(61, 71, 83, 0.22)',

  /* aerodrome and procedures */
  runway: '#e8edf3',
  runwayLabel: '#9aa6b4',
  aerodrome: '#57c8d8',
  centreline: '#2f3a45',
  centrelineTick: '#43505e',
  ilsCone: 'rgba(45, 92, 104, 0.28)',
  ilsEdge: '#2f5f6b',
  fafMark: '#57c8d8',
  chartLabel: '#7d8b9b',

  /* navigation */
  fix: '#4a5563',
  fixLabel: '#798798',
  fixBoundary: '#6f8091',
  route: '#6f7fd0',
  approachPath: '#57c8d8',

  /* traffic */
  target: '#e9eef5',
  targetGlow: 'rgba(233, 238, 245, 0.35)',
  targetSelected: '#ffc44d',
  history: '#6b7686',
  vector: '#aab6c5',
  leader: '#5b6675',

  /* data blocks */
  dataBlock: '#e9eef5',
  dataBlockSelected: '#ffc44d',
  dataBlockCaution: '#ffb020',
  dataBlockAlert: '#ff5f56',
  dataBlockDim: '#69737f',

  /* tools */
  ruler: '#ffc44d',
  scaleBar: '#5a6473',

  /* type */
  fontBlock: '11.5px "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace',
  fontLabel: '10px "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace',
  fontSmall: '9.5px "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace',
} as const;
