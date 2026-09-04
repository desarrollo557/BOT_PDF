import type { Job } from './types';

/**
 * A finished unit of work, summarised from what actually happened.
 *
 * Every field is read off the reports the workers produced. Nothing here is
 * estimated or rounded up from a projection: a report an operator is meant to
 * act on has to be the run, not a description of it.
 */
export interface Completion {
  id: string;
  kind: 'documento' | 'lote' | 'carpeta' | 'tanda';
  title: string;
  finishedAt: number;
  elapsedSeconds: number;
  /** Who was at the console. Attribution, never authorisation. */
  operator: string | null;

  documents: number;
  failedDocuments: number;
  pages: number;
  resolutions: number;
  bytes: number;
  reviewItems: number;
  repairs: number;
  quarantine: number;
  escalated: number;
  /** Where each page's answer came from, keyed by rung. */
  provenance: Record<string, number>;

  /** One line per document, for the detail table. */
  items: {
    jobId: string;
    filename: string;
    state: string;
    pages: number;
    resolutions: number;
    bytes: number;
    review: number;
    error: string | null;
  }[];

  /** Every resolution produced, in document order. */
  codes: { code: string; title: string | null; size: number; document: string }[];

  /** Only for a folder run. */
  destination?: string;
  delivered?: number;

  /** The units this report folds together. Only on a 'tanda'. */
  parts?: Completion[];
}

function stamp(value: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** Fold a set of finished jobs into one report. */
export function summarise(
  id: string,
  kind: Completion['kind'],
  title: string,
  jobs: Job[]
): Completion {
  const starts = jobs.map((job) => stamp(job.started_at)).filter(Boolean);
  const ends = jobs.map((job) => stamp(job.finished_at)).filter(Boolean);
  const from = starts.length ? Math.min(...starts) : 0;
  const to = ends.length ? Math.max(...ends) : Date.now();

  const provenance: Record<string, number> = {};
  const codes: Completion['codes'] = [];
  let pages = 0;
  let resolutions = 0;
  let reviewItems = 0;
  let repairs = 0;
  let quarantine = 0;
  let escalated = 0;

  for (const job of jobs) {
    const report = job.report;
    if (!report) continue;
    pages += report.page_count;
    // Cada clave se lee con red. Un informe de inventario no traía ninguna de
    // éstas y tumbaba el resumen entero -- y con él el modal de cierre, que es
    // lo único que le dice al operador que el trabajo terminó bien. Un informe
    // guardado por una versión anterior tampoco tiene por qué traerlas.
    resolutions += report.groups?.length ?? 0;
    reviewItems += report.review_queue?.length ?? 0;
    repairs += report.repairs?.length ?? 0;
    quarantine += report.quarantine?.length ?? 0;
    escalated += report.stats?.escalated ?? 0;
    for (const [rung, count] of Object.entries(report.stats?.by_provenance ?? {})) {
      provenance[rung] = (provenance[rung] ?? 0) + count;
    }
    for (const group of report.groups ?? []) {
      codes.push({
        code: group.code,
        title: group.title,
        size: group.size,
        document: job.filename
      });
    }
  }

  return {
    id,
    kind,
    title,
    finishedAt: to,
    elapsedSeconds: from ? Math.max(0, (to - from) / 1000) : 0,
    operator: jobs.find((job) => job.operator)?.operator ?? null,
    documents: jobs.length,
    failedDocuments: jobs.filter((job) => job.state === 'failed').length,
    pages,
    resolutions,
    bytes: jobs.reduce((sum, job) => sum + (job.bytes ?? 0), 0),
    reviewItems,
    repairs,
    quarantine,
    escalated,
    provenance,
    items: jobs.map((job) => ({
      jobId: job.id,
      filename: job.filename,
      state: job.state,
      pages: job.report?.page_count ?? 0,
      resolutions: job.report?.groups?.length ?? 0,
      bytes: job.bytes ?? 0,
      review: job.report?.review_queue?.length ?? 0,
      error: job.error
    })),
    codes
  };
}

/**
 * Fold several finished units into the single report of a whole run.
 *
 * Processing twenty files used to raise twenty modals: one appeared, the work
 * carried on behind it, and closing it only made room for the next. What the
 * operator is owed at the end is one answer about everything that ran, with the
 * per-file detail inside it -- so the individual reports stay whole in `parts`
 * and nothing here is a re-estimate: every total is the sum of what happened.
 */
export function merge(parts: Completion[]): Completion {
  const provenance: Record<string, number> = {};
  for (const part of parts) {
    for (const [rung, count] of Object.entries(part.provenance)) {
      provenance[rung] = (provenance[rung] ?? 0) + count;
    }
  }

  const add = (pick: (part: Completion) => number) =>
    parts.reduce((sum, part) => sum + pick(part), 0);

  const finishedAt = Math.max(...parts.map((part) => part.finishedAt));
  // El reloj de la tanda es el que vio la persona: desde que arrancó lo primero
  // hasta que terminó lo último. Sumar los tramos contaría en paralelo como si
  // fuera en fila y daría un número que nadie esperó.
  const startedAt = Math.min(
    ...parts.map((part) => part.finishedAt - part.elapsedSeconds * 1000)
  );

  return {
    id: `tanda:${parts.map((part) => part.id).join('|')}`,
    kind: 'tanda',
    title: `${parts.length} unidades procesadas`,
    finishedAt,
    elapsedSeconds: Math.max(0, (finishedAt - startedAt) / 1000),
    operator: parts.find((part) => part.operator)?.operator ?? null,
    documents: add((part) => part.documents),
    failedDocuments: add((part) => part.failedDocuments),
    pages: add((part) => part.pages),
    resolutions: add((part) => part.resolutions),
    bytes: add((part) => part.bytes),
    reviewItems: add((part) => part.reviewItems),
    repairs: add((part) => part.repairs),
    quarantine: add((part) => part.quarantine),
    escalated: add((part) => part.escalated),
    provenance,
    items: parts.flatMap((part) => part.items),
    codes: parts.flatMap((part) => part.codes),
    delivered: add((part) => part.delivered ?? 0) || undefined,
    parts
  };
}

/**
 * Completed runs, newest first, and whichever one is waiting to be shown.
 *
 * A report is raised once, when the work settles, and then kept: the operator
 * who stepped away still gets to read what happened, and the same report is
 * what the processed screen links back to.
 */
export class Reports {
  history = $state<Completion[]>([]);
  showing = $state<Completion | null>(null);

  #seen = new Set<string>();
  #watched = new Set<string>();
  /** Finished units waiting for the rest of the run to settle. */
  #pending: Completion[] = [];

  /**
   * Note that a unit is in flight right now.
   *
   * Only what this tab actually watched running is worth raising a modal for.
   * The service keeps finished runs in memory, so on every reload they arrive
   * again as "done" -- and without this, a refresh popped a report for work
   * that finished an hour ago.
   */
  watch(id: string): void {
    this.#watched.add(id);
  }

  /** Record a completion; it is raised later, once everything settles. */
  register(completion: Completion): void {
    if (this.#seen.has(completion.id)) return;
    this.#seen.add(completion.id);
    this.history = [completion, ...this.history];
    if (this.#watched.has(completion.id)) this.#pending.push(completion);
  }

  /**
   * Tell the store whether work is still running, and raise the report when it
   * is not.
   *
   * Nothing is shown while anything is still moving. Interrupting a run to
   * announce one file of it is what made the modal feel like an obstacle: the
   * queue kept going underneath and every close revealed another. One report
   * at the end, covering the lot.
   */
  settle(busy: boolean): void {
    if (busy || this.showing || !this.#pending.length) return;
    const waiting = this.#pending;
    this.#pending = [];
    this.showing = waiting.length === 1 ? waiting[0] : merge(waiting);
  }

  open(id: string): void {
    this.showing = this.history.find((item) => item.id === id) ?? null;
  }

  close(): void {
    this.showing = null;
  }
}

export const reports = new Reports();
