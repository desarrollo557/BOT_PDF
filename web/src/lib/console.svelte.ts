import { unitFor } from './format';
import { COUNTED_STAGES, rungForMark, STAGE_LABELS } from './rungs';
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
  /** Lo último que se registró de esta etapa, para no repetir la misma línea. */
  reported: number;
}

/**
 * Cada cuánto avance se deja una línea dentro de una etapa larga.
 *
 * Una línea por archivo son 287 líneas de un solo documento y el buffer deja de
 * poder leerse. Un tramo de veinte deja catorce, que es un ritmo al que se ve
 * avanzar sin perder de vista lo demás.
 */
const STAGE_STEP = 20;

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
    const stageChanged = previous !== undefined && previous.stage !== job.progress.stage;
    this.#snapshots.set(job.id, {
      ribbon: job.progress.ribbon,
      stage: job.progress.stage,
      state: job.state,
      reported: stageChanged ? 0 : (previous?.reported ?? 0)
    });
    if (job.state !== previous?.state) this.#recount();

    if (!previous) {
      this.#announce(job, scope);
      return;
    }
    if (job.progress.ribbon !== previous.ribbon) this.#diffPages(job, scope, previous.ribbon);
    if (job.progress.stage !== previous.stage) this.#stage(job, scope, previous);
    else this.#stageProgress(job, scope);
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
        // Una página marcada nunca se pliega en un resumen: es la línea del
        // buffer que hay que ver. Y se dice por qué está marcada, porque casi
        // nunca es que no se pudiera leer -- es que lo leído no cuadra, y sin
        // el motivo el operador tiene que abrir el documento para saberlo.
        const reason = job.progress.review?.[String(page)];
        this.push(
          'WARN',
          reason ? `página ${page} · ${reason}` : `página ${page} · enviada a revisión`,
          'warn',
          scope
        );
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

  /**
   * Entrada en una etapa: se cierra la anterior con su duración y se abre la nueva.
   *
   * Cerrarla con el tiempo que costó es lo que permite responder después a
   * "¿dónde se fue el minuto?", que es una pregunta distinta de "¿qué está
   * haciendo ahora?" y necesita que el dato haya quedado escrito.
   */
  #stage(job: Job, scope: string, previous: Snapshot): void {
    const progress = job.progress;
    if (COUNTED_STAGES.has(previous.stage) && previous.stage !== 'analysing') {
      const label = STAGE_LABELS[previous.stage] ?? previous.stage;
      this.push('STAGE', `${label} · terminado`, 'ok', scope);
    }

    const label = STAGE_LABELS[progress.stage] ?? progress.stage;
    const total = progress.stage_total ?? 0;
    const detail = progress.detail ? ` · ${progress.detail}` : '';
    if (COUNTED_STAGES.has(progress.stage) && progress.stage !== 'analysing') {
      this.push('STAGE', `${label}${total ? ` · ${total}` : ''}${detail}`, 'net', scope);
    }
  }

  /**
   * Avance dentro de una etapa larga, resumido por tramos.
   *
   * Sin esto una etapa sólo habla al empezar y al acabar, y entre medias -- que
   * puede ser un minuto escribiendo archivos -- la consola no tiene nada que
   * decir, que es exactamente cuando el operador se pregunta si sigue viva.
   */
  #stageProgress(job: Job, scope: string): void {
    const progress = job.progress;
    const stage = progress.stage;
    if (stage === 'analysing' || !COUNTED_STAGES.has(stage)) return;

    const done = progress.stage_done ?? 0;
    const total = progress.stage_total ?? 0;
    if (!total || !done) return;

    const snapshot = this.#snapshots.get(job.id);
    const reported = snapshot?.reported ?? 0;
    if (done !== total && done - reported < STAGE_STEP) return;
    if (done === reported) return;

    if (snapshot) snapshot.reported = done;
    const label = STAGE_LABELS[stage] ?? stage;
    const desde = reported + 1;
    const tramo = desde === done ? `${done}` : `${desde}–${done}`;
    this.push('STAGE', `${label} · ${tramo} de ${total}`, 'net', scope);
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

    // Un informe puede venir de un documento de resoluciones o de un libro de
    // folios, y cada uno trae lo suyo. Se lee siempre con red: un informe
    // guardado por una versión anterior no tiene por qué traer estas claves, y
    // que falte una nunca puede tumbar la pantalla entera.
    const groups = report.groups ?? [];
    const review = report.review_queue ?? [];
    const repairs = report.repairs ?? [];
    // Y se llaman por su nombre: "12 resoluciones" delante de un libro de
    // diplomas es una cifra correcta con la palabra equivocada.
    const unidad = unitFor(report, groups.length);

    this.push(
      'DONE',
      `${report.page_count} páginas → ${groups.length} ${unidad} en ${job.progress.elapsed_seconds.toFixed(1)} s`,
      'ok',
      scope
    );
    for (const group of groups.slice(0, 12)) {
      this.push('SPLIT', `${group.code}  ${group.size} pág.  ${group.title ?? 'sin título'}`, 'ok', scope);
    }
    if (groups.length > 12) {
      this.push('SPLIT', `… ${groups.length - 12} ${unidad} más`, 'ok', scope);
    }
    if (review.length) {
      this.push('WARN', `${review.length} páginas requieren revisión`, 'warn', scope);
    }
    for (const repair of repairs) {
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
