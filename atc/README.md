# Delhi Approach — a terminal radar control simulation

An approach/terminal radar sector for **VIDP (Indira Gandhi International, Delhi)**:
roughly 60 NM radius, surface to FL150. Vite + TypeScript, HTML5 canvas, no backend,
no database, no game engine.

This is one of two independent projects in the repository. It lives entirely in
`atc/` and shares nothing with the aerodynamics toolkit at the repository root — no
build, no dependencies, no code. See the [root README](../README.md) for that one.

> **Complete — milestone 5 of 5.** Per-type performance and fuel, wind aloft,
> published arrivals and departures, holding, ILS approaches flown to a landing,
> the safety net, five scenarios, scripted weather and emergencies, and a flight
> strip bay. Nothing here is a stub: every command listed below is implemented,
> and the known limitations are listed at the end rather than hidden.

---

## Running it on a Mac, step by step

If you have never used the terminal before, follow this exactly.

1. **Install Node.js.** Go to <https://nodejs.org>, download the **LTS** version
   for macOS (the Apple Silicon build is chosen automatically on an M-series Mac),
   open the downloaded `.pkg` file and click through the installer.

2. **Open the Terminal.** Press `Command` + `Space`, type `Terminal`, press `Return`.
   A window opens with a line of text and a cursor. You type commands here and press
   `Return` after each one.

3. **Go to the simulator's folder.** Type `cd ` — that is `cd` followed by a space,
   and do not press Return yet. Then, in the Finder, open the project folder and drag
   the **`atc`** folder inside it onto the Terminal window; it fills in the path for
   you. Now press `Return`.

   Everything below happens inside `atc`. If a command says "no such file or
   directory", you are probably in the folder above it — type `cd atc` and press
   `Return`.

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
   it into Safari or Chrome. The radar scope appears and traffic starts arriving.

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

## Scenarios

The **Scenarios** button in the top right lists the five that ship. Each runs from
its own seed, so the same scenario always plays out the same way; choosing one
starts a fresh session at `?scenario=<id>`.

| Scenario | What it is |
| --- | --- |
| **Tutorial** | Two scripted arrivals, no departures, light wind. Prompts in the comms panel tell you what to type. |
| **Standard day** | 20 movements an hour, runway 29 both ways. A normal shift. |
| **Evening rush** | 45 movements an hour with heavies mixed in, arrivals 29 and departures 28. The wake matrix will bite. |
| **Runway change** | The wind backs through the session, the ATIS rolls, and at 22 minutes the runway changes to 11. Traffic arrives short of fuel. |
| **Emergencies** | A normal flow, then an engine failure on a departure, and later a radio failure on an arrival that keeps flying its last clearance. |

Scenarios live in `src/data/scenarios/`. Each one names its traffic rates, its fleet
and airline mix, the entry fixes arrivals appear at, the SIDs departures are given,
its starting weather, and a list of timed events — a message, a weather change, a
runway change, an emergency, or a specific aircraft. The loader validates every
scenario against the airspace and the aircraft catalogue on boot: an unknown type, a
runway that does not exist, or an entry fix with no STAR published from it all fail
loudly rather than halfway through a session.

An emergency that has nobody to happen to — an engine failure scheduled for a
departure while every departure is still at the holding point — waits until there is
one, for up to twenty minutes, and then says it gave up.

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
| `AIC101 maintain 160 knots to 4 miles` | `AIC101 s 160 to 4` | Hold a speed on final until four miles out, then let the crew slow for landing. |
| `AIC101 reduce to minimum approach speed` | `AIC101 min` | Straight to the type's final approach speed, the whole way in. |
| `AIC101 cancel speed restriction` | `AIC101 resume normal speed` | Release the 250 kt below 10,000 ft rule for that aircraft. |
| `AIC101 proceed direct GUDUR` | `AIC101 dct GUDUR`, `AIC101 pd GUDUR` | Track to a published fix, then continue along the rest of its route. |
| `AIC101 squawk 4271` | `AIC101 sq 4271` | Assign a transponder code. Refused while an emergency squawk is set. |
| `IGO412 line up and wait runway 28` | `IGO412 luw 28` | Put a departure on the runway. |
| `IGO412 cleared for takeoff` | `IGO412 cft`, `IGO412 takeoff` | Send it. |
| `AIC101 say fuel remaining` | `AIC101 say fuel` | Ask for fuel on board. The crew answer in kilos and minutes at the current burn rate. |
| `AIC101 contact tower 118.1` | `AIC101 ct 118.1` | Hand the aircraft off. It acknowledges, stops taking your instructions, and drops off the scope once it is outside the sector. |

### Procedures

| Instruction | Abbreviated | Effect |
| --- | --- | --- |
| `AIC101 cleared ILS runway 29 approach` | `AIC101 ils 29` | Clear it for the approach. It keeps flying your heading until the localiser captures — and it only captures on a good intercept. |
| `AIC101 cancel approach` | — | Back onto vectors. Any heading, direct or hold does the same on its own. |
| `AIC101 go around` | `AIC101 ga` | Send it around: missed approach altitude, runway heading. |
| `AIC101 hold at GUDUR as published` | `AIC101 hold GUDUR` | Enter the published racetrack — published inbound course, turn direction, leg time and maximum speed. |
| `AIC101 hold at GUDUR expect further clearance 1420` | `AIC101 hold GUDUR efc 1420` | The same, with an EFC time the crew read back. |
| `AIC101 descend via the arrival` | `AIC101 dv` | Fly the published STAR restrictions — each fix's altitude and speed — rather than level-by-level clearances. |

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

The third field of the bottom line says what the aircraft is steering by:

| Field | Meaning |
| --- | --- |
| `TUMSA` | Tracking that fix, then the rest of its route. |
| `H270` | On a vector. |
| `HOLD GUDUR` | In the published pattern at that fix. |
| `→ILS29` | Cleared for the approach, still on your heading for it. |
| `‖ILS29` | Established on the localiser. |
| `▼ILS29` | On the glidepath. The cleared level changes to the runway elevation, because that is where it is going now. |

## Flying an approach

The whole point of the ILS here is that it can be flown badly.

- **The localiser captures on three conditions at once**: inside the published
  intercept range (18 NM), within 30° of the localiser course, and inside the beam
  — which narrows as you get closer to the runway. Miss any one of them and the
  aircraft flies straight through the centreline and tells you so. It is still
  cleared for the approach; it just needs another vector.
- **The glideslope is only ever captured from below**, when the path comes down to
  within about a dot of the aircraft. Hold one high and it will stay high, fly over
  the field, and go around at the missed approach point.
- **The gate at 1000 ft above the threshold**: off the centreline, off the slope,
  more than 25 kt above its final approach speed, or the runway still occupied, and
  the crew go around without being asked.
- **A landing aircraft holds the runway for 55 seconds.** Sequence tighter than that
  and the one behind goes around, on top of the wake turbulence minima below.
- **Speed on final is yours if you want it.** Clearing an approach hands speed back
  to the crew, who slow themselves: minimum clean by 5 NM, then the type's final
  approach speed. Assign a speed *after* that clearance and it holds instead, until
  the distance you name — `s 160 to 4` — or four miles if you name none. That is how
  spacing on final is actually worked, and it is the one instruction that can put an
  aircraft into the gate too fast to be stable. Once cleared for an approach an
  aircraft will also accept speeds below its clean minimum, because it is
  configuring; it will not go below its final approach speed.

Holding is a published racetrack — inbound course, turn direction, one minute legs,
maximum speed — flown as: track to the fix, turn outbound, run the leg, turn back
inbound. **Entry is simplified to a direct entry**; the parallel and teardrop entries
are not modelled.

The **strip bay** on the right lists everything inbound and everything waiting to
depart. Click a strip to select that aircraft, and drag an arrival strip to set the
order you intend to land them in.

## Departures

Taxi is abstracted: a departure appears at the holding point with its SID already
loaded, and shows up in the departure half of the strip bay. It is not on the radar
until it starts rolling — an aircraft at the holding point is the tower's.

```
IGO412 line up and wait runway 28      IGO412 luw 28
IGO412 cleared for takeoff             IGO412 cft
```

Lining up first is optional; a clearance to go implies it. Either is refused while
the runway is occupied. From the clearance onwards the take-off is modelled: the
aircraft accelerates at its own rate, rotates at its own speed, uses more runway on a
still day than into a headwind, and then climbs on its SID. A heading given to an
aircraft still on the ground is a heading to fly after departure.

It counts as a departure on the score once you have handed it on and it has left the
sector.

## Emergencies

| Tag | What happens |
| --- | --- |
| `ENG` | Engine failure. Squawks 7700, climbs at around 40% of its normal rate, and will not accept more than 250 kt however you ask. It wants the shortest track back to an approach. |
| `NORDO` | Radio failure. Squawks 7600, flies its last clearance and answers nothing. Your transmissions still go out — they are simply not acknowledged — so you have to move everyone else around it. |
| `EMG` | A fuel emergency, under 15 minutes' endurance. |

An aircraft with an emergency squawk will not let you change its code.

## The strip bay

Arrivals and departures are kept apart, as on a real bay. **Drag an arrival strip** to
set the order you intend to land them in; the number goes amber when a strip is out
of position against the order the traffic will actually arrive in. The order is
yours — the simulation does not act on it and does not correct it.

Each strip carries the callsign, type and wake category, what the aircraft is doing,
its level, its indicated airspeed and its range from the field. A coloured edge
marks anything the safety net is unhappy about. Click a strip to select the aircraft.

## The safety net

Everything the system notices appears in the **Safety net** panel, worst first, and
the aircraft it names turn amber or red on the scope. Amber is a prediction; red
means a minimum is being broken right now.

| Alert | What it means |
| --- | --- |
| `STCA` | Short term conflict alert. Amber and dashed for a loss predicted within two minutes; red and solid the moment the minima are actually broken. The line drawn between the pair is labelled with the present distance and vertical split. |
| `WAKE` | Wake turbulence in trail on final, inside 15 NM of the threshold. |
| `MSAW` | Terrain. Amber while descending towards the minimum safe altitude, red below it. |
| `EXIT` | An aircraft about to leave the sector, or already outside it, that you have not handed off. |

**Separation minima**: 3 NM and 1000 ft inside the terminal area, 5 NM as soon as
either aircraft is more than 40 NM from the field. The prediction assumes each
aircraft holds its present ground track and groundspeed and continues its present
climb or descent *until it reaches the level it is cleared to* — so an aircraft that
will level off safely does not raise an alert, and a turning aircraft occasionally
raises one that resolves itself. Both are what the real thing does.

**Wake turbulence minima** are in `src/data/wake.json`, following the ICAO Doc 4444
table. Rows are the aircraft in front:

| Behind ↓ / In front → | Super | Heavy | Medium | Light |
| --- | --- | --- | --- | --- |
| **Super** | 4 | 3 | 3 | 3 |
| **Heavy** | 6 | 4 | 3 | 3 |
| **Medium** | 7 | 5 | 3 | 3 |
| **Light** | 8 | 6 | 5 | 3 |

Nothing ever goes below the 3 NM radar minimum, and the loader refuses a matrix with
a hole in it or a figure below that minimum.

**MSAW is suppressed** once an aircraft is established on an approach — every
glidepath in the world goes below the sector minimum — and it stays silent where the
terrain grid publishes nothing, rather than inventing a figure.

## The session report

The **Score** button in the top right opens it. Nothing there is a points total;
these are the figures a watch supervisor would actually look at.

| Section | Figures |
| --- | --- |
| Movements | Arrivals landed, departures away, movements per hour, go-arounds. |
| Efficiency | Average and worst delay, total fuel burnt. |
| Safety | Separation losses, wake turbulence, terrain alerts, unhandled sector exits. |

**Delay** is measured per landed aircraft as the time it took over and above a
straight run from where it came on frequency to the threshold at its own normal
speed. It is never negative: beating the straight-line time means the wind helped,
not that you did.

Underneath is the **violation log** — one row per episode, with the time it started,
the aircraft involved, the minima that applied, the values at the closest point, when
that closest point occurred, and how long it lasted. An episode is logged once and
then tracked: the row keeps the *worst* values seen, not the first.

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

## Known limitations

These are things the simulation does not model, listed so that you know they are
absent rather than broken.

- **Simultaneous parallel operations.** VIDP has four near-parallel runways, and the
  simulation applies one set of radar minima everywhere, so running arrivals to one
  runway and departures off its neighbour can raise a conflict alert that real
  independent parallel approach procedures would not.
- **No ground movement.** Taxi is abstracted to a queue at the holding point; there
  is no apron, no taxiway, and no runway crossing.
- **Holding entries** are always direct entries; parallel and teardrop are not
  modelled.
- **The tower is not modelled.** You clear aircraft for the approach and for
  take-off yourself; there is no separate tower frequency doing it for you.
- **One controller position.** There is no coordination with anyone: handing off is
  a single instruction, and nobody hands anything to you.

---

## Approximated data

There are two data files, and **everything invented for the simulation in either of
them carries `"approximated": true`**.

### Wake turbulence — `src/data/wake.json`

This one is mostly **not** approximated: the matrix is the published ICAO Doc 4444
distance-based table, and the categories are the ICAO legacy ones. The single
invented figure is **super behind super**, taken as 4 NM, which Doc 4444 does not
publish; it is flagged in the file's `approximated` block.

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

Everything lives in this one file. **The aerodrome itself is now real; the airspace
around it is not.**

Taken from published sources, and correct:

| | |
| --- | --- |
| Runways | All four pairs: **09/27, 10/28, 11L/29R, 11R/29L** — the real designators. |
| Magnetic courses | 092/272, 098/278, 113/293. |
| Lengths and widths | 9,239 × 148 ft, 12,510 × 151 ft, 14,436 × 148 ft, 14,530 × 200 ft. |
| ILS frequencies | 109.10 (RWY 10), 111.90 (RWY 28), 112.40 (RWY 11L). |
| No ILS on 09/27 | Real, and modelled: clearing an aircraft for an approach to 09 or 27 is refused. |
| Elevation, reference point | 777 ft, 28°34′07″N 077°06′44″E. |

Sources: [SkyVector](https://skyvector.com/airport/VIDP/Indira-Gandhi-International-Airport),
[OurAirports](https://ourairports.com/airports/VIDP/runways.html),
[the AAI eAIP ILS RWY 11L plate](https://aim-india.aai.aero/eaip-v2-07-2024/eAIP/VIDP-ILS-RWY-11L-CAT-II-III.pdf),
[Wikipedia](https://en.wikipedia.org/wiki/Indira_Gandhi_International_Airport).

Everything else is still invented. It is geometrically self-consistent — fixes really do sit where their
bearings and distances say, final approach fixes really are 8.0 NM out on the
localiser course — but the numbers themselves need correcting from real charts before
you would call this VIDP.

Here is everything to check, by category:

| Object | Count | What is invented | What to correct from charts |
| --- | --- | --- | --- |
| `airport` | 1 | Invented: magnetic variation 0.6°E, transition altitude 4,000 ft, frequencies 127.9 / 118.1. **Elevation and the reference point are the published ones.** | AIP ENR/AD 2 VIDP. |
| `runways` | 8 ends | **Courses, lengths, widths and the three published ILS frequencies are real.** Still invented: where each strip sits relative to the reference point, the glideslope angle of 3.0°, the ILS frequencies of the reciprocals that open sources do not publish (29R, 11R, 29L), and the CAT categories other than 11L. | AD 2 VIDP runway table for the threshold coordinates; the ILS plates for the remaining frequencies. |
| `fixes` | 22 | Every one, including the names. GUDUR, TUMSA, SITAX, SOKAT, RAKMO, KIRAN, NOMAN, ROHTA, BUXOR, ALGAN, PARAS, LOHAT, VEDAN, MEHUL, DAULA, SAHIB are placed on chosen radials at 22 / 32 / 45 / 50 NM. The entry fixes sit at 50 NM so that the holding patterns published at them stay inside the sector. DIVEK, MOKAL, TARIL, SEKUR, BAGAN, NOPIL are the final approach fixes, placed 8.0 NM out. | STAR/SID charts and the ILS plates. Expect the real entry fixes and their names to differ entirely. |
| `sector.boundary` | 24 points | The whole polygon: a nominally 60 NM circle deliberately made slightly irregular, running between 57 and 67 NM. Ceiling FL150, floor surface. The loader refuses to start if a boundary fix ends up outside it. | The Delhi TMA lateral limits. |
| `airways` | 5 | W20, A201, G452, N563, L507 — the identifiers and the fixes on them. | ENR 3 route tables. |
| `sids` | 4 | GUDUR1D, RAKMO2E, NOMAN1F, BUXOR1G, including every altitude and speed restriction. | SID charts per runway. |
| `stars` | 5 | GUDUR1A, SITAX1B, RAKMO1C, NOMAN1H, BUXOR1J, including every restriction. | STAR charts. |
| `approaches` | 6 | One per runway that has a localiser. The **localiser courses are real**; intercept altitude 3,000 ft, intercept range 18 NM, FAF altitude 2,600 ft, decision heights and missed approach altitude 4,000 ft are invented. | ILS plates per runway. |
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
- Holding entries are always direct entries. The parallel and teardrop entries are
  not modelled, so an aircraft entering from an awkward angle flies a slightly
  larger first circuit than it would in life.
- Runway occupancy is a flat 55 seconds rather than a vacation time that depends on
  the aircraft, the exit taken and the surface.
- Conflict prediction samples the next two minutes every five seconds along straight
  tracks. A real STCA models the turn as well, and would not briefly light up on an
  aircraft that is already turning away.

---

## Adding a scenario

Copy one of the files in `src/data/scenarios/`, edit it, and add it to the list in
`src/sim/scenarios.ts`. The fields are:

| Field | What it does |
| --- | --- |
| `seed` | Drives every random choice. The same seed replays the same session. |
| `startTimeUtc`, `durationMin` | The clock, and how long the session runs. |
| `runways` | The configuration to start in. |
| `traffic.arrivalsPerHour`, `departuresPerHour` | The flow. Set both to zero for a fully scripted scenario. |
| `traffic.fleet`, `traffic.airlines` | Weighted mixes. Types must exist in `aircraft.json`. |
| `traffic.entryFixes` | Where arrivals appear. Each must have a STAR published from it. |
| `traffic.entryAltitudeFt`, `entrySpeedKt`, `fuelFactor` | How they arrive, and how much fuel they have. |
| `traffic.departureSids` | SIDs issued in rotation, filtered to those valid for the runway in use. |
| `weather` | The full starting weather, including the wind aloft. |
| `events` | Timed `message`, `weather`, `runway-change`, `emergency`, `arrival` and `departure` events. |

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
atc/
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
    │   ├── aircraft.json        performance profiles for the seven types
    │   ├── wake.json            wake turbulence separation matrix
    │   └── scenarios/           the five scenarios
    ├── sim/                     pure logic, no DOM, fully testable
    │   ├── units.ts             unit constants, rate limiting, formatting
    │   ├── geo.ts               local projection, bearings, distances, cross-track
    │   ├── rng.ts               seeded deterministic random numbers
    │   ├── types.ts             aircraft, clearance and comms types
    │   ├── airspace.ts          typed, validated view over airspace.json
    │   ├── weather.ts           weather state and METAR generation
    │   ├── flight.ts            turn geometry, wind triangle, vertical and speed
    │   ├── autoflight.ts        clearance to heading, fix tracking and sequencing
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

Tests sit next to what they test, as `*.test.ts`, and share one aircraft fixture in
`src/sim/testAircraft.ts`. They cover the command parser, turn geometry and the wind
triangle, performance interpolation and mass effects, fuel burn and the emergency
escalation, wind aloft and METAR generation, ILS geometry and every capture rule, the
holding pattern state machine, the wake matrix, separation standards and conflict
prediction, the safety net and its violation log, the score, the airspace loader,
data block layout and leader lines, and the simulation's determinism, handoff and
refusal behaviour, the scenario schema and all five shipped scenarios, traffic
generation and its reproducibility, the take-off roll and the departure clearances,
and the strip bay's ordering — including flying a complete approach to a landing,
blowing through the localiser, both kinds of go-around, a deliberate separation loss,
and a departure taken from the holding point to out of the sector — 341 tests in
seventeen files.

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
| 2 | Per-type performance profiles, mass, fuel, wind aloft, the rest of the basic commands | done |
| 3 | Published arrivals, holding and ILS flown: localiser and glideslope capture, go-arounds, arrivals sequenced to landing | done |
| 4 | Separation standards, wake matrix, STCA, MSAW, sector exit alerts, scoring and the violation log | done |
| 5 | Scenario files, weather events, departures and the runway queue, emergencies, flight strip bay | **this build** |

All five milestones are built. The SIDs, STARs, approaches and holds in
`airspace.json` are all flown, and the wake matrix, the terrain grid and the scenario
files are all used rather than merely present.
