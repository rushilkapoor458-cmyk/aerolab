/** The instruction vocabulary the controller can issue. */

import { TurnInstruction } from '../types.js';

export type Command =
  | { readonly kind: 'heading'; readonly headingDeg: number; readonly turn: TurnInstruction }
  | {
      readonly kind: 'altitude';
      readonly altitudeFt: number;
      readonly sense: 'climb' | 'descend' | 'maintain';
      readonly expedite: boolean;
    }
  | { readonly kind: 'speed'; readonly speedKt: number }
  | { readonly kind: 'speedCancel' }
  | { readonly kind: 'direct'; readonly fix: string }
  | { readonly kind: 'squawk'; readonly code: string }
  | { readonly kind: 'sayFuel' }
  | { readonly kind: 'approach'; readonly runway: string }
  | { readonly kind: 'cancelApproach' }
  | { readonly kind: 'goAround' }
  | { readonly kind: 'descendVia' }
  | {
      readonly kind: 'hold';
      readonly fix: string;
      /** Expect-further-clearance time, seconds since midnight, or null. */
      readonly efcTimeSec: number | null;
    }
  | {
      readonly kind: 'contact';
      /** Facility as spoken, e.g. "tower". Null when only a frequency was given. */
      readonly facility: string | null;
      readonly frequencyMhz: number;
    };

export interface ParsedLine {
  readonly callsign: string;
  readonly commands: readonly Command[];
}

export type ParseResult =
  | { readonly ok: true; readonly value: ParsedLine }
  | { readonly ok: false; readonly error: string };
