# Delhi Approach — a terminal radar control simulation

An approach/terminal radar sector for **VIDP (Indira Gandhi International, Delhi)**:
roughly 60 NM radius, surface to FL150. Vite + TypeScript, HTML5 canvas, no backend,
no database, no game engine.

> **Milestone 2 of 5.** The radar scope, the full flight model — per-type
> performance profiles, mass, fuel and wind aloft — and the basic command set.
> Enough to vector real traffic around the sector, watch a 777 struggle where a
> Q400 does not, and have an aircraft run itself short of fuel. The build order
> and what each later milestone adds are at the bottom of this file. Nothing here
> is a stub: every command listed below is implemented, and every feature not yet
> implemented is absent rather than faked.

---

## Running it on a Mac, step by step

If you have never used the terminal before, follow this exactly.

1. **Install Node.js.** Go to <https://nodejs.org>, download the **LTS** version
   for macOS (the Apple Silicon build is chosen automatically on an M-series Mac),
   open the downloaded `.pkg` file and click through the installer.

2. **Open the Terminal.** Press `Command` + `Space`, type `Terminal`, press `Return`.
   A window opens with a line of text and a cursor. You type commands here and press
   `Return` after each one.

3. **Go to the project folder.** Type `cd ` — that is `cd` followed by a space, and
   do not press Return yet. Then drag the project folder from the Finder onto the
   Terminal window; it fills in the path for you. Now press `Return`.

4. **Install the dependencies.** Type this and press `Return`:

   ```bash
   npm install
   ```

   It prints a few lines and takes a few seconds. You only ever do this once.

5. **Start it.** Type this and press `Return`:

   ```bash
   npm run dev
   ```

   It prints something like `Local: http://localhost:5173/`.

6. **Open it.** Hold `Command` and click that `http://localhost:5173/` link, or copy
   it into Safari or Chrome. The radar scope appears with four aircraft on frequency.

7. **Stop it** when you are done: click back on the Terminal window and press
   `Control` + `C`.

### The other commands

| Command | What it does |
| --- | --- |
| `npm run dev` | Start the simulator with live reloading. |
| `npm test` | Run the unit tests once. |
| `npm run test:watch` | Re-run the tests whenever a file changes. |
| `npm run typecheck` | Check the types without building. |
| `npm run build` | Type-check and produce a production build in `dist/`. |
| `npm run preview` | Serve the production build locally. |

---

## Flying the sector

Click an aircraft to select it — its callsign drops into the command line and its
route draws as a dashed line. Then type. Both full phraseology and the abbreviated
form are accepted, and you can chain as many instructions as you like onto one
callsign:

```
AIC101 turn left heading 270, descend and maintain 5000, reduce speed to 210
AIC101 tl 270 d 50 s 210
```

### Command reference

| Instruction | Abbreviated | Effect |
| --- | --- | --- |
| `AIC101 turn left heading 270` | `AIC101 tl 270` | Turn left onto magnetic heading 270. If left is the long way round, it goes the long way round. |
| `AIC101 turn right heading 090` | `AIC101 tr 090` | Turn right onto magnetic heading 090. |
| `AIC101 fly heading 270` | `AIC101 fh 270`, `AIC101 h 270` | Take up a heading the short way round. |
| `AIC101 descend and maintain 5000` | `AIC101 d 50`, `AIC101 d 5000` | Descend to 5,000 ft. |
| `AIC101 climb and maintain 9000` | `AIC101 c 90`, `AIC101 c FL150` | Climb. |
| `AIC101 maintain 7000` | `AIC101 m 70`, `AIC101 alt 7000` | Stop a climb or descent at a level. |
| `AIC101 expedite climb through 8000` | `AIC101 ex c 80` | Best rate through a level. `expedite descent` likewise. |
| `AIC101 reduce speed to 210` | `AIC101 s 210`, `AIC101 spd 210` | Assign an indicated airspeed. `increase speed to` also works. |
| `AIC101 cancel speed restriction` | `AIC101 resume normal speed` | Release the 250 kt below 10,000 ft rule for that aircraft. |
| `AIC101 proceed direct GUDUR` | `AIC101 dct GUDUR`, `AIC101 pd GUDUR` | Track to a published fix, then continue along the rest of its route. |
| `AIC101 squawk 4271` | `AIC101 sq 4271` | Assign a transponder code. Refused while an emergency squawk is set. |
| `AIC101 say fuel remaining` | `AIC101 say fuel` | Ask for fuel on board. The crew answer in kilos and minutes at the current burn rate. |
| `AIC101 contact tower 118.1` | `AIC101 ct 118.1` | Hand the aircraft off. It acknowledges, stops taking your instructions, and drops off the scope once it is outside the sector. |

Altitudes take either form: anything **600 or less is read as hundreds of feet**, so
`50` and `5000` both mean five thousand, and `FL150` means 15,000 ft. Headings are
**magnetic**, and because the aircraft points at the heading rather than tracking it,
you have to allow for the wind yourself — exactly as on the real job. An aircraft
proceeding direct to a fix works out its own crab angle.

Pilots read back what they can and say **unable, with a reason**, to what they cannot:
a descent below the minimum safe altitude for that patch of the sector, a level above
the top of the airspace, a climb instruction to an aircraft that is already above it,
a speed outside the envelope, or a fix that is not in the database. Part of a
transmission can be accepted while the rest is refused. Anything the parser cannot
read comes back as a message naming the offending word and showing a working example
— nothing ever fails silently.

### Keyboard and mouse

| Key | Effect |
| --- | --- |
| `Tab` | Complete the callsign. Press again to cycle through the aircraft that match. |
| `↑` / `↓` | Walk back and forth through what you have already sent. |
| `Enter` | Transmit. A line that will not parse stays in the box with the reason underneath. |
| `Space` | Pause and resume, when the command line is empty. |
| `?` | The in-game help overlay, when the command line is empty. |
| `Escape` | Clear the command line, or close the help overlay. |

| Mouse | Effect |
| --- | --- |
| Click a target | Select it, draw its route, put its callsign in the command line. |
| Click empty scope | Deselect. |
| Drag from a target | Measure range and magnetic bearing to any point. |
| Drag the scope | Pan. |
| Scroll wheel | Zoom about the pointer. |

### Reading a data block

```
AIC101 M          callsign and wake turbulence category (L, M, H, J)
110↓090           present altitude in hundreds of feet, trend arrow, cleared altitude
287 250 TUMSA     groundspeed, assigned speed, and the fix being tracked
```

The third field shows `H270` instead of a fix name when the aircraft is on a vector.
Blocks offset themselves automatically so they do not sit on top of each other or run
off the edge of the scope, and the leader line stops at the edge of the block rather
than striking through it.

A tag after the wake category, with the whole block recoloured, flags a state you
must not forget:

| Tag | Colour | Meaning |
| --- | --- | --- |
| `MIN` | amber | Minimum fuel advised: under 30 minutes' endurance, no undue delay. |
| `EMG` | red | Emergency declared: under 15 minutes, squawking 7700, wants priority. |
| `HO` | dimmed | Handed off to another frequency; no longer taking your instructions. |

### The `WX` button

Opens a debug panel that edits the weather live: surface wind direction and speed,
gusts, **the wind aloft and the altitude it applies at**, visibility, cloud, QNH,
temperature, dewpoint and the ATIS letter. The METAR in the ATIS panel regenerates as
you type and **the wind is felt by the aircraft on the very next step** — turn it
round and watch the ground tracks change. The panel also says which runway the wind
now favours, with a button to change the configuration.

The wind between the surface and the aloft altitude is interpolated, so an aircraft
at 13,000 ft is genuinely in a different airmass from one on base leg. Set the aloft
wind to 60 kt and watch the high traffic's groundspeeds separate from the low.

---

## What the flight model does

- **Turns.** Standard rate, 3°/sec, capped by a maximum bank of 25°, so a fast
  aircraft turns slower than standard rate — as it does in life. The bank rolls in and
  out at 3°/sec, and the roll-out is anticipated so the aircraft settles on the
  heading instead of overshooting. A turn you name a direction for commits to that
  direction, including the long way round.
- **Wind.** A proper wind triangle, using the wind *at the aircraft's altitude*. On a
  vector the aircraft points at the assigned magnetic heading and drifts; tracking a
  fix, it computes its own crab angle. True airspeed rises with altitude, so
  groundspeeds are not indicated airspeeds.
- **Performance, per type.** Seven profiles — A320, B738, B77W, A359, ATR72, Q400,
  C172 — each with its own climb and descent tables, speed envelope, acceleration
  limits, fuel burn and wake category. Nothing uses a flat rate:
  - climb rate falls off with altitude and falls further the heavier the aircraft is;
  - descent rate *rises* with altitude and is better when heavy, not worse;
  - an aircraft asked to descend and slow at the same time gets neither at full rate —
    the down-and-slow problem, modelled rather than described;
  - acceleration depends on the phase of flight (slowing in the descent is the hard
    case) and a steep turn eats into whatever thrust was spare;
  - a speed outside the type's envelope is refused, by that type's numbers.
- **Mass.** Each aircraft has an all-up mass that falls as it burns fuel, and the mass
  feeds straight back into the climb and descent rates.
- **Fuel.** Burn is per phase of flight. Under 30 minutes' endurance the crew advise
  minimum fuel; under 15 they declare an emergency, squawk 7700 and ask for priority,
  and the controller can no longer change their squawk. Dry tanks mean the aircraft
  cannot hold its level, whatever it is cleared to. `say fuel remaining` asks.
- **The 250 kt rule** below 10,000 ft is enforced until you cancel it per aircraft.

`SEJ301` starts with about thirty-five minutes of fuel, so if you leave it alone it
will work through both stages on its own.

Milestone 3 adds the procedures: SIDs, STARs, holding, and ILS approaches flown to a
landing — including blowing through the localiser on a bad intercept.

---

## Approximated data

There are two data files, and **everything invented for the simulation in either of
them carries `"approximated": true`**.

### Aircraft performance — `src/data/aircraft.json`

All seven profiles are approximated in full. The *shapes* are right — climb rate
falling with altitude, descent rate rising with it, jets accelerating better than
turboprops, burn highest in the climb — and they are internally consistent, but none
of the figures is manufacturer data. To correct a profile, replace these fields from
the aircraft's own performance manual or FCOM: `mass` (reference, minimum, maximum),
`speeds` (minimum clean, approach, maximum, typical cruise), `ceilingFt`, the
`climbRateFpm` and `descentRateFpm` tables, `acceleration` and `deceleration`,
`expediteFactor`, `fuelBurnKgPerHour` per phase, `fuelCapacityKg` and
`typicalArrivalFuelKg`. Wake categories are the one thing here taken from the real
world: L, M, H and J as ICAO defines them.

### Airspace — `src/data/airspace.json`

Everything lives in this one file. **Nothing in it is published chart data.** It is geometrically self-consistent — fixes really do sit where their
bearings and distances say, final approach fixes really are 8.0 NM out on the
localiser course — but the numbers themselves need correcting from real charts before
you would call this VIDP.

Here is everything to check, by category:

| Object | Count | What is invented | What to correct from charts |
| --- | --- | --- | --- |
| `airport` | 1 | Magnetic variation 0.6°E, transition altitude 4,000 ft, frequencies 127.9 / 118.1. Elevation 777 ft and the reference point are close to real. | AIP ENR/AD 2 VIDP. |
| `runways` | 6 | All six. True headings assumed as 092.6 / 102.6 / 112.6 and their reciprocals; threshold coordinates derived from an assumed layout around the reference point; lengths, widths, ILS frequencies, glideslope 3.0° and the CAT I / CAT IIIB categories. | AD 2 VIDP runway table and the ILS/DME charts. In reality the three runway pairs are not spaced 10° apart. |
| `fixes` | 22 | Every one, including the names. GUDUR, TUMSA, SITAX, SOKAT, RAKMO, KIRAN, NOMAN, ROHTA, BUXOR, ALGAN, PARAS, LOHAT, VEDAN, MEHUL, DAULA, SAHIB are placed on chosen radials at 22 / 32 / 45 / 55 NM. DIVEK, MOKAL, TARIL, SEKUR, BAGAN, NOPIL are the final approach fixes, placed 8.0 NM out. | STAR/SID charts and the ILS plates. Expect the real entry fixes and their names to differ entirely. |
| `sector.boundary` | 24 points | The whole polygon: a 60 NM circle deliberately made slightly irregular. Ceiling FL150, floor surface. | The Delhi TMA lateral limits. |
| `airways` | 5 | W20, A201, G452, N563, L507 — the identifiers and the fixes on them. | ENR 3 route tables. |
| `sids` | 4 | GUDUR1D, RAKMO2E, NOMAN1F, BUXOR1G, including every altitude and speed restriction. | SID charts per runway. |
| `stars` | 5 | GUDUR1A, SITAX1B, RAKMO1C, NOMAN1H, BUXOR1J, including every restriction. | STAR charts. |
| `approaches` | 6 | All six ILS approaches: intercept altitude 3,000 ft, intercept range 18 NM, FAF altitude 2,600 ft, decision heights, missed approach altitude 4,000 ft. Localiser courses inherit the invented runway bearings. | ILS plates per runway. |
| `holds` | 7 | All of them: inbound courses, turn directions, 60-second legs, 230 kt maximum, altitude bands. | Holding pattern data on the STAR and approach charts. |
| `msaGrid` | 625 cells | The entire terrain grid: 2,500 ft over the plain, 3,300 ft and 4,300 ft to the south-west for the Aravalli ridge, 3,000 ft outside 55 NM. | Area minimum altitude charts. |

Three further approximations are in code rather than data:

- Levels are spoken as flight levels at or above the transition altitude and as feet
  below it, but the simulation treats altitude as feet AMSL throughout — it does not
  model the QNH offset between an altitude and a flight level.
- True airspeed is derived from indicated airspeed by the 2%-per-1,000 ft rule of
  thumb, which is worth a couple of knots at the top of this sector.
- Wind is interpolated linearly between the surface report and a single wind aloft.
  A real forecast has a wind at every few thousand feet and a shear layer or two.

---

## Adding an aircraft type

Add an object to `types` in `src/data/aircraft.json` following the shape of the ones
already there — the loader validates that both rate tables are in ascending altitude
order and fails on boot if not. Then use its ICAO designator anywhere a type is named;
the wake category, speed envelope and every rate come from the profile, so nothing
else needs changing. A scenario naming a type with no profile is refused at once
rather than quietly flying a default.

## Adding another airport

`src/data/airspace.json` is the only file that knows about VIDP. Nothing in `src/sim`,
`src/render` or `src/ui` names a runway, a fix or a procedure. To swap airports:

1. Copy `src/data/airspace.json` to `src/data/<icao>.json` and edit it. Keep the
   schema: `airport`, `sector`, `runways`, `fixes`, `airways`, `sids`, `stars`,
   `approaches`, `holds`, `msaGrid`.
2. **All bearings and courses in the file are TRUE degrees.** The simulation converts
   to magnetic for display and for your instructions using
   `airport.magneticVariationDeg` (positive east). Do not mix the two.
3. Set `airport.referencePoint` to the aerodrome reference point. It becomes the
   origin of the internal flat-earth projection, so everything else should be within
   a hundred miles or so of it.
4. Give the MSA grid an origin at its south-west corner, a cell size in NM, and a row
   of values per band running west to east, starting from the southernmost band.
5. Point `src/main.ts` at the new file:

   ```ts
   import airspaceData from './data/<icao>.json';
   ```

6. Start it. The loader validates the file on boot and refuses to run if a procedure
   names a fix or runway that does not exist, or if the MSA grid does not match its
   declared size — the reason is printed on the page, not hidden in the console.

---

## Layout

```
.
├── index.html                   page shell and panel markup
├── package.json                 scripts and dependencies
├── tsconfig.json                strict TypeScript, no implicit any
├── vite.config.ts               dev server and build
├── vitest.config.ts             unit tests
└── src/
    ├── main.ts                  entry point: load airspace, build world, start loop
    ├── style.css                scope-dark theme for the surrounding panels
    ├── data/
    │   ├── airspace.json        the whole of VIDP — the only airport-specific file
    │   └── aircraft.json        performance profiles for the seven types
    ├── sim/                     pure logic, no DOM, fully testable
    │   ├── units.ts             unit constants, rate limiting, formatting
    │   ├── geo.ts               local projection, bearings, distances, cross-track
    │   ├── rng.ts               seeded deterministic random numbers
    │   ├── types.ts             aircraft, clearance and comms types
    │   ├── airspace.ts          typed, validated view over airspace.json
    │   ├── weather.ts           weather state and METAR generation
    │   ├── flight.ts            turn geometry, wind triangle, vertical and speed
    │   ├── autoflight.ts        clearance to heading, fix tracking and sequencing
    │   ├── initialTraffic.ts    milestone 1 hand-placed traffic
    │   ├── world.ts             the Simulation: step, transmit, comms
    │   └── commands/
    │       ├── types.ts         the instruction vocabulary
    │       ├── parser.ts        phraseology and abbreviations to commands
    │       └── execute.ts       applying commands, readbacks and refusals
    ├── render/                  canvas only, reads the simulation, never writes it
    │   ├── theme.ts             scope colours
    │   ├── camera.ts            world to screen, pan and zoom
    │   ├── datablock.ts         data block text and automatic offsetting
    │   └── scope.ts             the scope itself
    └── ui/                      DOM panels
        ├── app.ts               animation loop, mouse, keyboard, wiring
        ├── commandBar.ts        history, Tab completion, error display
        ├── comms.ts             scrolling communications panel
        ├── statusBar.ts         clock, ATIS, runways, wind, simulation rate
        ├── debugPanel.ts        live weather editing
        └── help.ts              the ? overlay
```

Tests sit next to what they test, as `*.test.ts`. They cover the command parser, turn
geometry and the wind triangle, performance interpolation and mass effects, fuel burn
and the emergency escalation, wind aloft and METAR generation, the airspace loader,
data block layout and leader lines, and the simulation's determinism, handoff and
refusal behaviour — 156 tests in eight files.

```bash
npm test
```

---

## Determinism

The scenario seed is fixed in `src/main.ts` (`SEED`). All randomness goes through
`src/sim/rng.ts`, and the flight model integrates on a fixed 0.25-second substep
regardless of frame rate, so the same seed reproduces the same session exactly —
including at 2× and 4×, and including when the simulation is stepped in one large
piece rather than many small ones. Both properties are asserted in
`src/sim/world.test.ts`.

---

## Build order

| Milestone | Scope | State |
| --- | --- | --- |
| 1 | Radar scope, turn geometry, wind, command bar | done |
| 2 | Per-type performance profiles, mass, fuel, wind aloft, the rest of the basic commands | **this build** |
| 3 | SIDs, STARs, holding and ILS flown: localiser and glideslope capture, go-arounds, arrivals sequenced to landing | next |
| 4 | Separation standards, wake matrix, STCA, MSAW, sector exit alerts, scoring and the violation log | |
| 5 | Scenario files, generated weather, emergencies, flight strip bay, polish | |

The airspace data for milestone 3 — SIDs, STARs, ILS approaches, holds — is already in
`airspace.json` and validated on load, and each profile already carries the approach
speed the aircraft will fly on final; milestone 3 is the flying of it, not the
authoring of it.
