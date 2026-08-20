/**
 * Wiring: the animation loop, the mouse, and the panels.
 *
 * This is the only module that knows about both the simulation and the DOM.
 */

import { Point } from '../sim/geo.js';
import { Aircraft } from '../sim/types.js';
import { Simulation } from '../sim/world.js';
import { RadarScope, Ruler } from '../render/scope.js';
import { ScreenPoint } from '../render/camera.js';
import { CommandBar } from './commandBar.js';
import { CommsPanel } from './comms.js';
import { DebugPanel } from './debugPanel.js';
import { HelpOverlay } from './help.js';
import { SequencePanel } from './sequence.js';
import { StatusBar, requireElement, requireInput } from './statusBar.js';

/** Simulated seconds may never advance by more than this in one frame. */
const MAX_FRAME_STEP_SEC = 1.0;
/** Movement below this many pixels counts as a click, not a drag. */
const CLICK_SLOP_PX = 4;

type DragMode = 'none' | 'pan' | 'ruler';

export class App {
  private readonly canvas: HTMLCanvasElement;
  private readonly scope: RadarScope;
  private readonly statusBar: StatusBar;
  private readonly comms: CommsPanel;
  private readonly sequence: SequencePanel;
  private readonly commandBar: CommandBar;
  private readonly help: HelpOverlay;

  private rate = 1;
  private lastFrameMs = 0;
  private panelTimerSec = 0;

  private selectedId: string | null = null;
  private dragMode: DragMode = 'none';
  private dragStart: ScreenPoint = { x: 0, y: 0 };
  private dragLast: ScreenPoint = { x: 0, y: 0 };
  private dragMoved = false;
  private rulerFromId: string | null = null;
  private rulerTo: Point | null = null;

  constructor(private readonly sim: Simulation) {
    const canvas = document.getElementById('scope');
    if (!(canvas instanceof HTMLCanvasElement)) throw new Error('index.html is missing #scope');
    this.canvas = canvas;

    this.scope = new RadarScope(canvas, sim);
    this.statusBar = new StatusBar(sim, (rate) => this.setRate(rate));
    this.comms = new CommsPanel(requireElement('comms-log'));
    this.sequence = new SequencePanel(requireElement('sequence-list'), sim, (id) => {
      this.select(this.sim.aircraft.find((a) => a.id === id) ?? null);
    });
    this.help = new HelpOverlay(requireElement('help-overlay'));
    new DebugPanel(sim);

    this.commandBar = new CommandBar(requireInput('command-input'), requireElement('command-error'), {
      onSubmit: (line) => this.sim.transmit(line),
      callsigns: () => this.sim.aircraft.map((a) => a.callsign),
      onTogglePause: () => this.setRate(this.rate === 0 ? 1 : 0),
      onToggleHelp: () => this.help.toggle(),
    });

    requireElement('help-toggle').addEventListener('click', () => {
      this.help.toggle();
      this.commandBar.focus();
    });

    this.bindPointer();
    this.bindKeyboard();
    window.addEventListener('resize', () => this.scope.resize());
  }

  start(): void {
    this.lastFrameMs = performance.now();
    this.statusBar.update(this.rate);
    this.comms.update(this.sim.comms);
    this.sequence.update(this.selectedId);
    const frame = (nowMs: number): void => {
      this.tick(nowMs);
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }

  private tick(nowMs: number): void {
    const elapsedSec = Math.min(MAX_FRAME_STEP_SEC, (nowMs - this.lastFrameMs) / 1000);
    this.lastFrameMs = nowMs;

    if (this.rate > 0) {
      this.sim.step(elapsedSec * this.rate);
      this.panelTimerSec += elapsedSec;
    }

    // Panels are cheap but not free; a quarter of a second is fast enough
    // for a clock and a comms log.
    if (this.panelTimerSec > 0.25 || this.rate === 0) {
      this.panelTimerSec = 0;
      this.statusBar.update(this.rate);
      this.comms.update(this.sim.comms);
      this.sequence.update(this.selectedId);
    }

    this.scope.render({ selectedId: this.selectedId, ruler: this.currentRuler() });
  }

  private currentRuler(): Ruler | null {
    if (this.rulerFromId === null || this.rulerTo === null) return null;
    const from = this.sim.aircraft.find((a) => a.id === this.rulerFromId);
    if (from === undefined) return null;
    return { from: from.position, to: this.rulerTo };
  }

  private setRate(rate: number): void {
    this.rate = rate;
    this.statusBar.update(rate);
  }

  private select(ac: Aircraft | null): void {
    this.selectedId = ac === null ? null : ac.id;
    if (ac !== null) this.commandBar.prefill(ac.callsign);
  }

  /* ------------------------------------------------------------ pointer */

  private bindPointer(): void {
    const canvas = this.canvas;

    canvas.addEventListener('pointerdown', (event) => {
      canvas.setPointerCapture(event.pointerId);
      const screen = this.eventPoint(event);
      this.dragStart = screen;
      this.dragLast = screen;
      this.dragMoved = false;

      const target = this.scope.aircraftAt(screen);
      if (target !== null) {
        this.dragMode = 'ruler';
        this.rulerFromId = target.id;
        this.rulerTo = this.scope.camera.toWorld(screen);
      } else {
        this.dragMode = 'pan';
      }
    });

    canvas.addEventListener('pointermove', (event) => {
      if (this.dragMode === 'none') return;
      const screen = this.eventPoint(event);
      if (Math.hypot(screen.x - this.dragStart.x, screen.y - this.dragStart.y) > CLICK_SLOP_PX) {
        this.dragMoved = true;
      }
      if (this.dragMode === 'pan') {
        this.scope.camera.panByPixels(screen.x - this.dragLast.x, screen.y - this.dragLast.y);
      } else {
        this.rulerTo = this.scope.camera.toWorld(screen);
      }
      this.dragLast = screen;
    });

    const finish = (event: PointerEvent): void => {
      if (this.dragMode === 'none') return;
      const screen = this.eventPoint(event);
      if (!this.dragMoved) {
        this.select(this.scope.aircraftAt(screen));
      }
      this.dragMode = 'none';
      this.rulerFromId = null;
      this.rulerTo = null;
    };
    canvas.addEventListener('pointerup', finish);
    canvas.addEventListener('pointercancel', finish);

    canvas.addEventListener(
      'wheel',
      (event) => {
        event.preventDefault();
        const factor = Math.pow(0.999, event.deltaY);
        this.scope.camera.zoomAt(this.eventPoint(event), factor);
      },
      { passive: false },
    );

    // The scope is a drawing surface, not a document: no text selection.
    canvas.addEventListener('contextmenu', (event) => event.preventDefault());
  }

  private eventPoint(event: MouseEvent): ScreenPoint {
    const rect = this.canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  /* ----------------------------------------------------------- keyboard */

  private bindKeyboard(): void {
    document.addEventListener('keydown', (event) => {
      const target = event.target;
      const typing = target instanceof HTMLInputElement || target instanceof HTMLSelectElement;

      if (event.key === 'Escape' && this.help.isOpen) {
        event.preventDefault();
        this.help.hide();
        this.commandBar.focus();
        return;
      }
      if (typing) return; // The command bar handles its own keys.

      if (event.key === '?') {
        event.preventDefault();
        this.help.toggle();
      } else if (event.key === ' ') {
        event.preventDefault();
        this.setRate(this.rate === 0 ? 1 : 0);
      }
    });
  }
}
