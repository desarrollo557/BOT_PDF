/**
 * Who is operating the separator, and since when.
 *
 * There is no password, and the screens say so. This is not access control and
 * must never be mistaken for it: anyone at the machine can type any name. What
 * it buys is real anyway -- every document carries the operator who ran it, so
 * the inventory can answer "who processed this", and a shift has a beginning
 * and an end instead of one endless session nobody owns.
 */

export type SessionState = 'anonymous' | 'active' | 'idle';

export interface Operator {
  name: string;
  /** Free text: "Archivo central", "Ventanilla 3". Optional. */
  station: string | null;
  startedAt: number;
}

const STORAGE_KEY = 'resolutions.session';

/**
 * Inactivity before the session parks itself.
 *
 * Not a lock -- one click resumes it, because there is nothing to unlock. It is
 * a checkpoint: a console left open overnight should not keep attributing the
 * next morning's work to whoever walked away from it.
 */
export const IDLE_AFTER_MS = 60 * 60 * 1000;

/** How often the clock is checked. Cheap: one comparison. */
const TICK_MS = 30_000;

interface Stored {
  operator: Operator;
  lastSeen: number;
}

function read(): Stored | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Stored;
    if (!parsed?.operator?.name) return null;
    return parsed;
  } catch {
    // A private window, cleared site data, a browser that blocks storage: all
    // mean "no session", never a crash on the way to the login screen.
    return null;
  }
}

function write(value: Stored | null): void {
  try {
    if (value === null) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Storage is a convenience here. Losing it costs a re-entry of a name.
  }
}

/**
 * The session, as an explicit machine.
 *
 *   anonymous --open()-->  active
 *   active    --idle-->    idle        (an hour without a click)
 *   idle      --resume()-> active      (one click; there is nothing to unlock)
 *   idle      --close()--> anonymous
 *   active    --close()--> anonymous
 *
 * Every transition is a method. Nothing outside this file writes the state,
 * which is what keeps "who is logged in" answerable from one place.
 */
export class Session {
  state = $state<SessionState>('anonymous');
  operator = $state<Operator | null>(null);
  lastSeen = $state(Date.now());
  /** Ticks so elapsed time re-renders without every screen owning a clock. */
  now = $state(Date.now());

  #timer: ReturnType<typeof setInterval> | null = null;
  #detach: (() => void) | null = null;

  get name(): string | null {
    return this.operator?.name ?? null;
  }

  get elapsedSeconds(): number {
    if (!this.operator) return 0;
    return Math.max(0, (this.now - this.operator.startedAt) / 1000);
  }

  get idleSeconds(): number {
    return Math.max(0, (this.now - this.lastSeen) / 1000);
  }

  /** Restore a session from storage and start watching for inactivity. */
  start(): () => void {
    const stored = read();
    if (stored) {
      this.operator = stored.operator;
      this.lastSeen = stored.lastSeen;
      this.state = Date.now() - stored.lastSeen > IDLE_AFTER_MS ? 'idle' : 'active';
    }

    const touch = () => this.touch();
    const events: (keyof WindowEventMap)[] = ['pointerdown', 'keydown', 'wheel', 'focus'];
    for (const event of events) window.addEventListener(event, touch, { passive: true });

    this.#timer = setInterval(() => {
      this.now = Date.now();
      if (this.state === 'active' && this.now - this.lastSeen > IDLE_AFTER_MS) {
        this.state = 'idle';
      }
    }, TICK_MS);

    this.#detach = () => {
      for (const event of events) window.removeEventListener(event, touch);
      if (this.#timer) clearInterval(this.#timer);
      this.#timer = null;
    };
    return () => this.stop();
  }

  stop(): void {
    this.#detach?.();
    this.#detach = null;
  }

  // -- transitions ------------------------------------------------------------

  open(name: string, station: string | null = null): boolean {
    const clean = name.trim();
    if (!clean) return false;
    this.operator = { name: clean, station: station?.trim() || null, startedAt: Date.now() };
    this.state = 'active';
    this.#persist();
    return true;
  }

  resume(): void {
    if (this.state !== 'idle') return;
    this.state = 'active';
    this.#persist();
  }

  close(): void {
    this.operator = null;
    this.state = 'anonymous';
    write(null);
  }

  /** Any interaction keeps the session alive; from idle it does not resume. */
  touch(): void {
    this.now = Date.now();
    this.lastSeen = this.now;
    if (this.state === 'active') this.#persist();
  }

  #persist(): void {
    this.lastSeen = Date.now();
    this.now = this.lastSeen;
    if (this.operator) write({ operator: this.operator, lastSeen: this.lastSeen });
  }
}

export const session = new Session();
