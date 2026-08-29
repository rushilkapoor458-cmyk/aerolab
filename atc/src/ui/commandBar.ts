/**
 * The command line.
 *
 * Up and down walk the history, Tab completes a callsign, Enter transmits.
 * With the line empty, space pauses and ? opens the help overlay, so the
 * controller never has to take their hands off the keyboard.
 */

export interface CommandBarHandlers {
  /** Send a line. Returns an error message to display, or null on success. */
  readonly onSubmit: (line: string) => string | null;
  /** Callsigns currently on frequency, for Tab completion. */
  readonly callsigns: () => readonly string[];
  readonly onTogglePause: () => void;
  readonly onToggleHelp: () => void;
}

export class CommandBar {
  private readonly history: string[] = [];
  private historyIndex = 0;
  private completionMatches: string[] = [];
  private completionIndex = 0;
  private lastCompletion = '';

  constructor(
    private readonly input: HTMLInputElement,
    private readonly errorBox: HTMLElement,
    private readonly handlers: CommandBarHandlers,
  ) {
    this.input.addEventListener('keydown', (event) => this.onKeyDown(event));
    this.input.addEventListener('input', () => this.resetCompletion());
    this.input.focus();
  }

  /** Put a callsign in the box, as clicking a target does. */
  prefill(callsign: string): void {
    this.input.value = `${callsign} `;
    this.input.focus();
    this.input.setSelectionRange(this.input.value.length, this.input.value.length);
    this.clearError();
  }

  focus(): void {
    this.input.focus();
  }

  private onKeyDown(event: KeyboardEvent): void {
    switch (event.key) {
      case 'Enter':
        event.preventDefault();
        this.submit();
        return;
      case 'ArrowUp':
        event.preventDefault();
        this.recall(-1);
        return;
      case 'ArrowDown':
        event.preventDefault();
        this.recall(1);
        return;
      case 'Tab':
        event.preventDefault();
        this.complete();
        return;
      case 'Escape':
        event.preventDefault();
        this.input.value = '';
        this.clearError();
        return;
      case ' ':
        if (this.input.value.length === 0) {
          event.preventDefault();
          this.handlers.onTogglePause();
        }
        return;
      case '?':
        if (this.input.value.length === 0) {
          event.preventDefault();
          this.handlers.onToggleHelp();
        }
        return;
      default:
        return;
    }
  }

  private submit(): void {
    const line = this.input.value.trim();
    if (line.length === 0) return;
    const error = this.handlers.onSubmit(line);
    this.history.push(line);
    this.historyIndex = this.history.length;
    if (error === null) {
      this.input.value = '';
      this.clearError();
    } else {
      // Leave the text in place so a typo can be corrected rather than retyped.
      this.input.select();
      this.showError(error);
    }
    this.resetCompletion();
  }

  private recall(direction: -1 | 1): void {
    if (this.history.length === 0) return;
    this.historyIndex = Math.min(this.history.length, Math.max(0, this.historyIndex + direction));
    this.input.value = this.historyIndex === this.history.length ? '' : (this.history[this.historyIndex] ?? '');
    this.input.setSelectionRange(this.input.value.length, this.input.value.length);
    this.resetCompletion();
  }

  /**
   * Tab completes the callsign, which is always the first token. Pressing it
   * again cycles through the other aircraft whose callsign shares the prefix.
   */
  private complete(): void {
    const value = this.input.value;
    const cycling = this.completionMatches.length > 0 && value === this.lastCompletion;

    if (!cycling) {
      const firstSpace = value.indexOf(' ');
      if (firstSpace !== -1) return; // Past the callsign; nothing else completes yet.
      const token = value.toUpperCase();
      this.completionMatches = this.handlers
        .callsigns()
        .filter((c) => token.length === 0 || c.startsWith(token))
        .sort();
      this.completionIndex = 0;
    } else {
      this.completionIndex = (this.completionIndex + 1) % this.completionMatches.length;
    }

    const match = this.completionMatches[this.completionIndex];
    if (match === undefined) return;
    this.input.value = `${match} `;
    this.lastCompletion = this.input.value;
    this.input.setSelectionRange(this.input.value.length, this.input.value.length);
  }

  private resetCompletion(): void {
    this.completionMatches = [];
    this.completionIndex = 0;
    this.lastCompletion = '';
  }

  private showError(message: string): void {
    this.errorBox.textContent = message;
    this.errorBox.hidden = false;
  }

  private clearError(): void {
    this.errorBox.textContent = '';
    this.errorBox.hidden = true;
  }
}
