import { rungForMark } from './rungs';
import type { Job } from './types';

export type Level = 'sys' | 'net' | 'page' | 'model' | 'ok' | 'warn' | 'fail';

export interface LogLine {
  id: number;
  time: string;
  tag: string;
  level: Level;
  scope: string | null;
  text: string;
}

/**
 * Lines kept in the buffer.
 *
 * A batch of fifty documents produces thousands of lines; the console is a live
 * window, not an archive, and an unbounded list is a memory leak that only
 * shows up on the runs that matter.
 */
const MAX_LINES = 600;

/**
 * Page changes in one frame above which the lines collapse into a single range.
 *
 * Frames arrive four times a second with eight page workers behind them, so a
 * fast document would otherwise scroll past faster than anyone can read it.
 */
const BURST_LIMIT = 4;

const PENDING = '.';

interface Snapshot {
  ribbon: string;
  stage: string;
  state: string;
}

function stamp(): string {
  const now = new Date();
  const pad = (value: number, size = 2) => String(value).padStart(size, '0');
  return `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}.${pad(now.getMilliseconds(), 3)}`;
}

function shorten(name: string, size = 22): string {
  return name.length <= size ? name : `${name.slice(0, size - 4)}…${name.slice(-3)}`;
}

function ranged(pages: number[]): string {
  if (pages.length === 1) return `${pages[0]}`;
  return `${pages[0]}–${pages[pages.length - 1]}`;
}

/**
 * The live activity log behind the terminal panel.
 *
 * Every line is derived from the job frames the browser already receives, by
 * diffing each new ribbon against the last one seen. No extra endpoint, no
 * second stream, and nothing added to the events a document already emits.
 */
class ConsoleLog {
  lines = $state<LogLine[]>([]);
  paused = $state(false);
  /** Documents queued or running, for the status light on the panel. */
  active = $state(0);

  #next = 0;
  #snapshots = new Map<string, Snapshot>();

  push(tag: string, text: string, level: Level = 'sys', scope: string | null = null): void {
    if (this.paused) return;
    const line: LogLine = { id: this.#next++, time: stamp(), tag, level, scope, text };
    const kept = this.lines.length >= MAX_LINES ? this.lines.slice(-(MAX_LINES - 1)) : this.lines;
    this.lines = [...kept, line];
  }

  clear(): void {
    this.lines = [];
    this.push('SYS', 'consola limpiada', 'sys');
  }

  /** Fold one job frame into the log, emitting only what changed since the last. */
  ingest(job: Job): void {
    const scope = shorten(job.filename);
    const previous = this.#snapshots.get(job.id);
    this.#snapshots.set(job.id, {
      ribbon: job.progress.ribbon,
      stage: job.progress.stage,
      state: job.state
    });
    if (job.state !== previous?.state) this.#recount();

    if (!previous) {
      this.#announce(job, scope);
      return;
    }
    if (job.progress.ribbon !== previous.ribbon) this.#diffPages(job, scope, previous.ribbon);
    if (job.progress.stage !== previous.stage) this.#stage(job, scope);
    if (job.state !== previous.state) this.#state(job, scope);
  }

  #recount(): void {
    let running = 0;
    for (const snapshot of this.#snapshots.values()) {
      if (snapshot.state === 'queued' || snapshot.state === 'running') running += 1;
    }
    this.active = running;
  }

  /** First sight of a job: state it once instead of replaying its whole history. */
  #announce(job: Job, scope: string): void {
    if (job.state === 'done') {
      this.#state(job, scope);
      return;
    }
    if (job.state === 'failed') {
      this.push('FAIL', job.error ?? 'el documento falló', 'fail', scope);
      return;
    }
    if (job.progress.page_count) {
      this.push('OPEN', `${job.progress.page_count} páginas · analizando`, 'net', scope);
    } else {
      this.push('QUEUE', 'en cola', 'sys', scope);
    }
  }

  #diffPages(job: Job, scope: string, before: string): void {
    const after = job.progress.ribbon;
    const total = job.progress.page_count || after.length;
    const width = String(total).length;
    const read: number[] = [];
    const tally = new Map<string, number>();

    for (let index = 0; index < after.length; index++) {
      const mark = after[index];
      const was = before[index] ?? PENDING;
      if (mark === was || mark === PENDING) continue;
      const page = index + 1;

      if (mark === 'x') {
        // A page nobody could read is never folded into a summary: it is the
        // one line in the buffer that has to be seen.
        this.push('WARN', `página ${page} ilegible · enviada a revisión`, 'warn', scope);
        continue;
      }
      if (was !== PENDING) {
        // A page already answered and now repainted came back from the model.
        this.push(
          'MODEL',
          `página ${page} reprocesada · ${rungForMark(mark)?.label ?? 'releída'}`,
          'model',
          scope
        );
        continue;
      }

      read.push(page);
      tally.set(mark, (tally.get(mark) ?? 0) + 1);
    }

    if (!read.length) return;

    if (read.length <= BURST_LIMIT) {
      for (const page of read) {
        const label = rungForMark(after[page - 1])?.label ?? 'leída';
        this.push(
          'PAGE',
          `${String(page).padStart(width, '0')}/${total}  ${label.toLowerCase()}`,
          'page',
          scope
        );
      }
      return;
    }

    const breakdown = [...tally.entries()]
      .map(([mark, count]) => `${count} ${rungForMark(mark)?.label.toLowerCase() ?? mark}`)
      .join(', ');
    this.push('PAGE', `${ranged(read)} · ${read.length} páginas — ${breakdown}`, 'page', scope);
  }

  #stage(job: Job, scope: string): void {
    if (job.progress.stage === 'grouping') {
      this.push('GROUP', 'agrupando páginas por resolución', 'net', scope);
    } else if (job.progress.stage === 'assembling') {
      this.push('WRITE', 'escribiendo los PDF de salida', 'net', scope);
    }
  }

  #state(job: Job, scope: string): void {
    if (job.state === 'running') {
      const pages = job.progress.page_count ? ` · ${job.progress.page_count} páginas` : '';
      this.push('OPEN', `documento abierto${pages}`, 'net', scope);
      return;
    }
    if (job.state === 'failed') {
      this.push('FAIL', job.error ?? 'el documento falló', 'fail', scope);
      return;
    }
    if (job.state !== 'done') return;

    const report = job.report;
    if (!report) {
      this.push('DONE', 'listo', 'ok', scope);
      return;
    }

    this.push(
      'DONE',
      `${report.page_count} páginas → ${report.groups.length} resoluciones en ${job.progress.elapsed_seconds.toFixed(1)} s`,
      'ok',
      scope
    );
    for (const group of report.groups.slice(0, 12)) {
      this.push('SPLIT', `${group.code}  ${group.size} pág.  ${group.title ?? 'sin título'}`, 'ok', scope);
    }
    if (report.groups.length > 12) {
      this.push('SPLIT', `… ${report.groups.length - 12} resoluciones más`, 'ok', scope);
    }
    if (report.review_queue.length) {
      this.push('WARN', `${report.review_queue.length} páginas requieren revisión`, 'warn', scope);
    }
    for (const repair of report.repairs) {
      this.push(
        'FIX',
        `página ${repair.page}: ${repair.observed} → ${repair.applied} (ruido de OCR)`,
        'warn',
        scope
      );
    }
  }
}

export const consoleLog = new ConsoleLog();
