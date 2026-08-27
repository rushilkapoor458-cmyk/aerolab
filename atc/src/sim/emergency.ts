/**
 * Emergencies other than fuel: an engine failure and a radio failure.
 *
 * Both are declared by the crew, not by the controller, and both change what
 * the aircraft can do rather than merely labelling it.
 */

import { Aircraft, EmergencyState } from './types.js';

export const ENGINE_FAILURE_SQUAWK = '7700';
export const RADIO_FAILURE_SQUAWK = '7600';

/** What an engine-out aircraft has left of its climb performance. */
export const ENGINE_OUT_PERFORMANCE_FACTOR = 0.4;
/** The fastest an engine-out aircraft will accept. */
export const ENGINE_OUT_MAX_SPEED_KT = 250;

/** Declare an engine failure. Returns the call the crew make. */
export function declareEngineFailure(ac: Aircraft): string {
  ac.emergency = 'engine';
  ac.squawk = ENGINE_FAILURE_SQUAWK;
  ac.performanceFactor = ENGINE_OUT_PERFORMANCE_FACTOR;
  ac.clearance.expedite = false;
  ac.clearance.speedKt = Math.min(ac.clearance.speedKt, ENGINE_OUT_MAX_SPEED_KT);
  return (
    `MAYDAY MAYDAY MAYDAY, ${ac.callsign}, engine failure, squawking ${ENGINE_FAILURE_SQUAWK}, ` +
    `request immediate return and priority landing`
  );
}

/**
 * Declare a radio failure. The aircraft carries on with its last clearance
 * and stops answering — the controller has to work around it.
 */
export function declareRadioFailure(ac: Aircraft): string {
  ac.emergency = 'radio';
  ac.squawk = RADIO_FAILURE_SQUAWK;
  return `${ac.callsign} is squawking ${RADIO_FAILURE_SQUAWK} — no reply on frequency`;
}

/** True when the aircraft will not answer the controller at all. */
export function isOutOfContact(ac: Aircraft): boolean {
  return ac.emergency === 'radio';
}

/** Short label for the data block. */
export function emergencyTag(state: EmergencyState): string {
  switch (state) {
    case 'engine':
      return 'ENG';
    case 'radio':
      return 'NORDO';
    default:
      return '';
  }
}
