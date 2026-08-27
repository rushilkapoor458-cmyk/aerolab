/**
 * Scope palette and type.
 *
 * A vector radar display: a near-black ground, a restrained green for the
 * map, brighter green for the traffic, and colour used only where it carries
 * meaning — amber for attention, red for an emergency.
 */

export const THEME = {
  /* ground and map */
  background: '#03110a',
  vignette: 'rgba(0, 0, 0, 0.35)',
  rangeRing: '#0f3623',
  rangeRingMajor: '#16492f',
  rangeRingLabel: '#1d6a44',
  compassTick: '#164a30',
  compassTickMajor: '#22764c',
  compassLabel: '#2c8d5d',
  boundary: '#1d7a4b',
  boundaryGlow: 'rgba(29, 122, 75, 0.25)',

  /* aerodrome */
  runway: '#a8f5c8',
  aerodrome: '#4fbf85',
  centreline: '#1b6a44',
  centrelineTick: '#2a8f5c',
  ilsCone: 'rgba(20, 84, 54, 0.55)',
  ilsEdge: '#1f7a4e',
  fafMark: '#3fb87c',

  /* navigation */
  fix: '#2c8f62',
  fixLabel: '#3aae76',
  fixBoundary: '#49c98b',
  route: '#7f74e8',
  approachPath: '#c08adf',

  /* traffic */
  target: '#78ffb8',
  targetGlow: 'rgba(120, 255, 184, 0.5)',
  targetSelected: '#ffd166',
  history: '#2f9a67',
  vector: '#4fd694',
  leader: '#2c8a5f',

  /* data blocks */
  dataBlock: '#8dffc4',
  dataBlockSelected: '#ffd166',
  dataBlockCaution: '#ffb020',
  dataBlockAlert: '#ff5c5c',
  dataBlockDim: '#3f7a5c',

  /* tools */
  ruler: '#ffd166',
  scaleBar: '#2c8d5d',

  /* type */
  fontBlock: '11.5px "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace',
  fontLabel: '10px "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace',
  fontSmall: '9.5px "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace',
} as const;
