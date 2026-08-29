/** The scenarios that ship with the simulator. */

import emergency from '../data/scenarios/emergency.json';
import rush from '../data/scenarios/rush.json';
import standardDay from '../data/scenarios/standard-day.json';
import tutorial from '../data/scenarios/tutorial.json';
import weather from '../data/scenarios/weather.json';
import { Scenario } from './scenario.js';

/** Listed in the order a controller would work through them. */
export const SCENARIOS: readonly Scenario[] = [
  tutorial as unknown as Scenario,
  standardDay as unknown as Scenario,
  rush as unknown as Scenario,
  weather as unknown as Scenario,
  emergency as unknown as Scenario,
];

export const DEFAULT_SCENARIO_ID = 'standard-day';

export function findScenario(id: string): Scenario | undefined {
  return SCENARIOS.find((s) => s.id === id);
}
