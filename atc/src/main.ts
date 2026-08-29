/** Entry point: load the airspace, build the world, start the loop. */

import './style.css';
import airspaceData from './data/airspace.json';
import aircraftData from './data/aircraft.json';
import wakeData from './data/wake.json';
import { Airspace, RawAirspace } from './sim/airspace.js';
import { PerformanceCatalogue, RawPerformance } from './sim/performance.js';
import { RawWakeMatrix, WakeMatrix } from './sim/wake.js';
import { DEFAULT_SCENARIO_ID, findScenario } from './sim/scenarios.js';

import { Simulation } from './sim/world.js';
import { App } from './ui/app.js';

/** Which scenario to run: `?scenario=rush`, defaulting to a normal shift. */
function requestedScenarioId(): string {
  const requested = new URLSearchParams(window.location.search).get('scenario');
  return requested === null || requested.length === 0 ? DEFAULT_SCENARIO_ID : requested;
}

function boot(): void {
  const airspace = new Airspace(airspaceData as unknown as RawAirspace);
  const performance = new PerformanceCatalogue(aircraftData as unknown as RawPerformance);
  const wake = new WakeMatrix(wakeData as unknown as RawWakeMatrix);

  const id = requestedScenarioId();
  const scenario = findScenario(id);
  if (scenario === undefined) {
    throw new Error(`There is no scenario called "${id}". Try ?scenario=${DEFAULT_SCENARIO_ID}.`);
  }

  // The scenario's own seed drives every random choice in the session, so the
  // same scenario always plays out the same way.
  const sim = new Simulation(airspace, performance, wake, scenario.seed);
  sim.loadScenario(scenario);
  new App(sim).start();
}

try {
  boot();
} catch (error) {
  // A broken data file is the likeliest cause; say so on the page rather
  // than leaving a black screen and a console message nobody opened.
  const message = error instanceof Error ? error.message : String(error);
  document.body.innerHTML =
    `<pre style="color:#ff6b6b;padding:24px;white-space:pre-wrap;font:13px monospace">` +
    `Could not start the simulation.\n\n${message}</pre>`;
  throw error;
}
