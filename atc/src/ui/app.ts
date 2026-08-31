/**
 * Wiring: the animation loop, the mouse, and the panels.
 *
 * This is the only module that knows about both the simulation and the DOM.
 */

import { Point } from '../sim/geo.js';
import { Aircraft } from '../sim/types.js';
import { Simulation } from '../sim/world.js';
import { GroundChart } from '../render/groundChart.js';
import { RadarScope, Ruler } from '../render/scope.js';
import { ScreenPoint } from '../render/camera.js';
import { CommandBar } from './commandBar.js';
import { CommsPanel } from './comms.js';
import { DebugPanel } from './debugPanel.js';
import { HelpOverlay } from './help.js';
import { AlertsPanel } from './alerts.js';
import { ScoreOverlay } from './score.js';
import { ScenarioPicker } from './scenarioPicker.js';
import { StripBay } from './strips.js';
import { StatusBar, requireButton, requireElement, requireInput } from './statusBar.js';
import { Readback, VoiceControl } from './voice.js';

/** Simulated seconds may never advance by more than this in one frame. */
const MAX_FRAME_STEP_SEC = 1.0;
/** Movement below this many pixels counts as a click, not a drag. */
const CLICK_SLOP_PX = 4;

type DragMode = 'none' | 'pan' | 'ruler';

export class App {
  private readonly canvas: HTMLCanvasElement;
  private readonly scope: RadarScope;
  private readonly groundChart: GroundChart;
  private readonly statusBar: StatusBar;
  private readonly comms: CommsPanel;
  private readonly strips: StripBay;
  private readonly scenarios: ScenarioPicker;
  private readonly alerts: AlertsPanel;
  private readonly score: ScoreOverlay;
  private readonly commandBar: CommandBar;
  private readonly help: HelpOverlay;
  private readonly voice: VoiceControl;
  private readonly readback: Readback;
  private readonly voiceStatus: HTMLElement;
  /** Comms entries already spoken, so a readback is never said twice. */
  private lastSpokenCommsId = 0;

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

    const groundCanvas = document.getElementById('ground-chart');
    if (!(groundCanvas instanceof HTMLCanvasElement)) {
      throw new Error('index.html is missing #ground-chart');
    }
    this.groundChart = new GroundChart(groundCanvas, sim.airspace);
    this.statusBar = new StatusBar(sim, (rate) => this.setRate(rate));
    this.comms = new CommsPanel(requireElement('comms-log'));
    const selectById = (id: string): void => {
      this.select(this.sim.aircraft.find((a) => a.id === id) ?? null);
    };
    this.strips = new StripBay(
      requireElement('arrival-strips'),
      requireElement('departure-strips'),
      sim,
      selectById,
    );
    this.scenarios = new ScenarioPicker(requireElement('scenario-overlay'), sim.scenario);
    this.alerts = new AlertsPanel(requireElement('alerts-list'), selectById);
    this.score = new ScoreOverlay(requireElement('score-overlay'), sim);
    this.help = new HelpOverlay(requireElement('help-overlay'));
    new DebugPanel(sim);

    this.commandBar = new CommandBar(requireInput('command-input'), requireElement('command-error'), {
      onSubmit: (line) => this.sim.transmit(line),
      callsigns: () => this.sim.aircraft.map((a) => a.callsign),
      onTogglePause: () => this.setRate(this.rate === 0 ? 1 : 0),
      onToggleHelp: () => this.help.toggle(),
    });

    requireElement('help-toggle').addEventListener('click', () => {
      this.score.hide();
      this.scenarios.hide();
      this.help.toggle();
      this.commandBar.focus();
    });

    requireElement('score-toggle').addEventListener('click', () => {
      this.help.hide();
      this.scenarios.hide();
      this.score.toggle();
      this.commandBar.focus();
    });

    requireElement('scenario-toggle').addEventListener('click', () => {
      this.help.hide();
      this.score.hide();
      this.scenarios.toggle();
    });

    this.voiceStatus = requireElement('voice-status');
    this.readback = new Readback();
    this.voice = new VoiceControl(requireButton('mic-button'), {
      onTranscript: (line) => this.commandBar.setLine(line),
      onSubmit: (line) => this.sim.transmit(line),
      onStatus: (message) => this.showVoiceStatus(message),
    });

    // Say so once, at startup, rather than leaving a dead button to be
    // discovered by holding it and getting nothing.
    if (!this.voice.available) {
      this.showVoiceStatus(
        'Voice needs Chrome, Edge or Safari. The typed command line works everywhere.',
      );
    }

    const readbackButton = requireButton('readback-toggle');
    if (!this.readback.available) {
      readbackButton.disabled = true;
      readbackButton.title = 'This browser cannot speak.';
    }
    readbackButton.addEventListener('click', () => {
      this.readback.setEnabled(!this.readback.isEnabled);
      readbackButton.classList.toggle('active', this.readback.isEnabled);
      // Start from the present; do not read out the whole backlog.
      this.lastSpokenCommsId = this.sim.comms.at(-1)?.id ?? 0;
      this.commandBar.focus();
    });

    this.bindPointer();
    this.bindKeyboard();
    window.addEventListener('resize', () => {
      this.scope.resize();
      this.groundChart.resize();
    });
  }

  start(): void {
    this.lastFrameMs = performance.now();
    this.statusBar.update(this.rate);
    this.comms.update(this.sim.comms);
    this.strips.update(this.selectedId);
    this.alerts.update(this.sim.safety.alerts);
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
      this.strips.update(this.selectedId);
      this.alerts.update(this.sim.safety.alerts);
      this.speakNewReadbacks();
    }

    this.scope.render({
      selectedId: this.selectedId,
      ruler: this.currentRuler(),
      alerts: this.sim.safety.alerts,
    });
    this.groundChart.render(this.sim.aircraft, this.selectedId);
  }

  /**
   * Read the pilots' replies aloud.
   *
   * Only what the crews say — the controller's own transmissions are already
   * known to whoever sent them, and hearing your own clearance read back to
   * you by the machine is just noise.
   */
  private speakNewReadbacks(): void {
    if (!this.readback.isEnabled) return;
    for (const entry of this.sim.comms) {
      if (entry.id <= this.lastSpokenCommsId) continue;
      this.lastSpokenCommsId = entry.id;
      if (entry.source === 'pilot') this.readback.say(entry.text);
    }
  }

  /** Show, or clear, the line under the command bar that voice writes to. */
  private showVoiceStatus(message: string): void {
    this.voiceStatus.textContent = message;
    this.voiceStatus.hidden = message === '';
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

      const overlayOpen = this.help.isOpen || this.score.isOpen || this.scenarios.isOpen;
      if (event.key === 'Escape' && overlayOpen) {
        event.preventDefault();
        this.help.hide();
        this.score.hide();
        this.scenarios.hide();
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
