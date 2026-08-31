/**
 * Push-to-talk voice control, and spoken pilot readbacks.
 *
 * Hold the key (or the mic button), speak, release: the recogniser's best
 * guess is normalised into command-line text, shown in the command bar so you
 * can see what it heard, and transmitted. Releasing is what ends the
 * transmission, exactly as a real PTT does, which is also why this is more
 * accurate than leaving the microphone open — the recogniser is told where
 * the utterance stops instead of guessing from a pause.
 *
 * Everything here is browser API and DOM. The mapping from spoken words to
 * command text lives in ./voiceTranscript, which is pure and tested.
 *
 * Availability is not assumed. Speech recognition is a Chrome, Edge and
 * Safari feature; Firefox has none, and any browser can refuse the microphone.
 * Every path through this module has to leave the typed command line working,
 * because that is the fallback.
 */

import { normaliseTranscript } from './voiceTranscript.js';

/**
 * The slice of the Web Speech API this uses.
 *
 * It is declared here rather than imported because TypeScript's DOM library
 * does not carry SpeechRecognition — it is still prefixed in every shipping
 * browser.
 */
interface SpeechRecognitionAlternativeLike {
  readonly transcript: string;
  readonly confidence: number;
}
interface SpeechRecognitionResultLike {
  readonly length: number;
  readonly isFinal: boolean;
  item: (index: number) => SpeechRecognitionAlternativeLike;
  readonly [index: number]: SpeechRecognitionAlternativeLike;
}
interface SpeechRecognitionResultListLike {
  readonly length: number;
  item: (index: number) => SpeechRecognitionResultLike;
  readonly [index: number]: SpeechRecognitionResultLike;
}
interface SpeechRecognitionEventLike extends Event {
  readonly resultIndex: number;
  readonly results: SpeechRecognitionResultListLike;
}
interface SpeechRecognitionErrorEventLike extends Event {
  readonly error: string;
}
interface SpeechRecognitionLike extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
}
type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

interface SpeechWindow {
  SpeechRecognition?: SpeechRecognitionConstructor;
  webkitSpeechRecognition?: SpeechRecognitionConstructor;
}

function recognitionConstructor(): SpeechRecognitionConstructor | null {
  const w = window as unknown as SpeechWindow;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** The key held to talk. Backquote sits where a PTT switch would. */
const PTT_KEY = '`';

export interface VoiceHandlers {
  /** Put recognised text in the command bar for the controller to see. */
  readonly onTranscript: (line: string) => void;
  /** Send a recognised line. Returns an error to display, or null. */
  readonly onSubmit: (line: string) => string | null;
  /** Show a message about the microphone itself. */
  readonly onStatus: (message: string) => void;
}

export class VoiceControl {
  private recognition: SpeechRecognitionLike | null = null;
  private listening = false;
  private transcript = '';

  constructor(
    private readonly button: HTMLButtonElement,
    private readonly handlers: VoiceHandlers,
  ) {
    const Recognition = recognitionConstructor();
    if (Recognition === null) {
      this.button.disabled = true;
      this.button.title =
        'This browser has no speech recognition. Chrome, Edge or Safari can do it; ' +
        'the typed command line works everywhere.';
      this.button.classList.add('unavailable');
      return;
    }

    const recognition = new Recognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-IN';
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => this.onResult(event);
    recognition.onerror = (event) => this.onError(event);
    recognition.onend = () => this.onEnd();
    this.recognition = recognition;

    this.button.title = `Hold to talk (or hold ${PTT_KEY})`;
    this.bindButton();
    this.bindKey();
  }

  /** Whether this browser can do it at all, for the help overlay to report. */
  get available(): boolean {
    return this.recognition !== null;
  }

  private bindButton(): void {
    this.button.addEventListener('mousedown', (e) => {
      e.preventDefault();
      this.start();
    });
    this.button.addEventListener('mouseup', () => this.finish());
    this.button.addEventListener('mouseleave', () => {
      if (this.listening) this.finish();
    });
    // Touch, so the button works on a tablet as well as a mouse.
    this.button.addEventListener('touchstart', (e) => {
      e.preventDefault();
      this.start();
    }, { passive: false });
    this.button.addEventListener('touchend', (e) => {
      e.preventDefault();
      this.finish();
    }, { passive: false });
  }

  private bindKey(): void {
    window.addEventListener('keydown', (event) => {
      if (event.key !== PTT_KEY || event.repeat) return;
      // The key is also a character. Swallow it so it never reaches the box.
      event.preventDefault();
      this.start();
    });
    window.addEventListener('keyup', (event) => {
      if (event.key !== PTT_KEY) return;
      event.preventDefault();
      this.finish();
    });
  }

  private start(): void {
    if (this.recognition === null || this.listening) return;
    this.transcript = '';
    this.listening = true;
    this.button.classList.add('listening');
    this.handlers.onStatus('Listening…');
    try {
      this.recognition.start();
    } catch {
      // start() throws if the engine has not finished stopping from the last
      // transmission. The onend handler clears that state; drop this press
      // rather than leaving the button stuck lit.
      this.listening = false;
      this.button.classList.remove('listening');
      this.handlers.onStatus('Microphone busy — try again.');
    }
  }

  /** Release: stop listening and send whatever was heard. */
  private finish(): void {
    if (this.recognition === null || !this.listening) return;
    this.listening = false;
    this.button.classList.remove('listening');
    try {
      this.recognition.stop();
    } catch {
      /* already stopped; the transcript below is still good */
    }
    this.submitTranscript();
  }

  private submitTranscript(): void {
    const line = normaliseTranscript(this.transcript);
    this.transcript = '';
    if (line === '') {
      this.handlers.onStatus('Nothing heard — say again.');
      return;
    }
    this.handlers.onTranscript(line);
    const error = this.handlers.onSubmit(line);
    this.handlers.onStatus(error ?? '');
  }

  private onResult(event: SpeechRecognitionEventLike): void {
    let heard = '';
    for (let i = 0; i < event.results.length; i += 1) {
      const result = event.results[i];
      if (result === undefined || result.length === 0) continue;
      const alternative = result[0];
      if (alternative !== undefined) heard += `${alternative.transcript} `;
    }
    this.transcript = heard.trim();
    // Show what it is hearing as it hears it, so a misrecognition is visible
    // before the key comes up rather than after the clearance has gone.
    if (this.listening && this.transcript !== '') {
      this.handlers.onStatus(`Listening… “${this.transcript}”`);
    }
  }

  private onError(event: SpeechRecognitionErrorEventLike): void {
    this.listening = false;
    this.button.classList.remove('listening');
    const message =
      event.error === 'not-allowed' || event.error === 'service-not-allowed'
        ? 'Microphone blocked. Allow it in the browser, or type the clearance.'
        : event.error === 'no-speech'
          ? 'Nothing heard — say again.'
          : `Speech recognition error: ${event.error}`;
    this.handlers.onStatus(message);
  }

  private onEnd(): void {
    this.listening = false;
    this.button.classList.remove('listening');
  }
}

/**
 * Spoken pilot readbacks.
 *
 * Speech synthesis is far more widely supported than recognition, but it is
 * still optional, and a readback that never arrives must not stall anything —
 * so every call here is fire-and-forget.
 */
export class Readback {
  private readonly synth: SpeechSynthesis | null =
    typeof window !== 'undefined' && 'speechSynthesis' in window ? window.speechSynthesis : null;

  private enabled = false;

  get available(): boolean {
    return this.synth !== null;
  }

  setEnabled(on: boolean): void {
    this.enabled = on;
    if (!on) this.synth?.cancel();
  }

  get isEnabled(): boolean {
    return this.enabled;
  }

  /**
   * Say a pilot's reply.
   *
   * Readbacks arrive faster than they can be spoken when the scope is busy or
   * the clock is running at 4x, so a backlog is dropped rather than queued —
   * a readback for a clearance three transmissions ago is worse than silence.
   */
  say(text: string): void {
    if (this.synth === null || !this.enabled || text === '') return;
    if (this.synth.speaking || this.synth.pending) return;

    const utterance = new SpeechSynthesisUtterance(spoken(text));
    utterance.rate = 1.15;
    utterance.pitch = 1;
    utterance.volume = 0.9;
    utterance.lang = 'en-IN';
    this.synth.speak(utterance);
  }
}

/**
 * Make written phraseology sound like radio.
 *
 * Numbers are the whole problem in reverse: "29R" read by a synthesiser comes
 * out "twenty-nine R", where a pilot says "two niner right". Altitudes stay as
 * whole numbers, because that is how they are spoken.
 */
export function spoken(text: string): string {
  let out = text;

  // Runway designators, before bare digits get split up.
  out = out.replace(/\b(\d{1,2})([LRC])\b/g, (_m, n: string, side: string) => {
    const word = side === 'L' ? 'left' : side === 'R' ? 'right' : 'centre';
    return `${digits(n)} ${word}`;
  });

  // Flight levels.
  out = out.replace(/\bFL(\d{2,3})\b/g, (_m, n: string) => `flight level ${digits(n)}`);

  // Altitudes in whole thousands are spoken as numbers, so leave them alone
  // and only split the short groups: headings, speeds, squawks.
  out = out.replace(/\b(\d{3,4})\b/g, (m) => (Number(m) >= 1000 && Number(m) % 100 === 0 ? m : digits(m)));

  return out;
}

/** "270" -> "2 7 0", with the aviation nine. */
function digits(group: string): string {
  return group
    .split('')
    .map((d) => (d === '9' ? 'niner' : d))
    .join(' ');
}
