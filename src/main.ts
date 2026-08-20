/** Entry point: load the airspace, build the world, start the loop. */

import './style.css';
import airspaceData from './data/airspace.json';
import { Airspace, RawAirspace } from './sim/airspace.js';
import { seedMilestoneOneTraffic } from './sim/initialTraffic.js';
import { Simulation } from './sim/world.js';
import { App } from './ui/app.js';

/** Fixed seed: the same session every time until the scenarios land. */
const SEED = 20260820;

function boot(): void {
  const airspace = new Airspace(airspaceData as unknown as RawAirspace);
  const sim = new Simulation(airspace, SEED);
  seedMilestoneOneTraffic(sim);
  new App(sim).start();
}

try {
  boot();
} catch (error) {
  // A broken airspace.json is the likeliest cause; say so on the page rather
  // than leaving a black screen and a console message nobody opened.
  const message = error instanceof Error ? error.message : String(error);
  document.body.innerHTML =
    `<pre style="color:#ff6b6b;padding:24px;white-space:pre-wrap;font:13px monospace">` +
    `Could not start the simulation.\n\n${message}</pre>`;
  throw error;
}
