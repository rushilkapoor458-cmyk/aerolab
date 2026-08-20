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
