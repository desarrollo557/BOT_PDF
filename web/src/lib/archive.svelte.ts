import type { Entry } from './components/ProcessedCard.svelte';
import type { Job, ProcessedDocument } from './types';

/**
 * The archive's filtering and ordering, kept out of the screen that draws it.
 *
 * Pure functions over plain data: what an operator can narrow by, and the one
 * order the list is allowed to be in at any moment. Separated so both are
 * testable without rendering anything.
 */

export type Period = 'hoy' | 'semana' | 'mes' | 'todo';
export type Status = 'todos' | 'revision' | 'limpios' | 'fallidos';
export type Sort = 'reciente' | 'antiguo' | 'resoluciones' | 'paginas' | 'nombre';

export interface Filters {
  text: string;
  period: Period;
  status: Status;
  operator: string;
}

export const EMPTY_FILTERS: Filters = {
  text: '',
  period: 'todo',
  status: 'todos',
  operator: 'todos'
};

const DAY = 86_400_000;

function stamp(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** A live job as the archive sees it. */
export function fromJob(job: Job): Entry {
  return {
    key: `job:${job.id}`,
    jobId: job.id,
    name: job.filename,
    at: stamp(job.finished_at) || stamp(job.created_at) || Date.now(),
    resolutions: job.report?.groups?.length ?? 0,
    pages: job.report?.page_count ?? 0,
    bytes: job.bytes ?? 0,
    review: job.report?.review_queue?.length ?? 0,
    operator: job.operator,
    codes: job.report?.groups?.map((group) => group.code) ?? [],
    failed: job.state === 'failed',
    error: job.error,
    live: true
  };
}

/** A ledger row as the archive sees it. Same shape, so it draws the same. */
export function fromHistory(entry: ProcessedDocument): Entry {
  return {
    key: `hist:${entry.job_id}`,
    jobId: entry.job_id,
    name: entry.source_document,
    at: stamp(entry.processed_at),
    resolutions: entry.resolutions,
    pages: entry.source_pages || entry.pages,
    bytes: entry.bytes ?? 0,
    review: entry.review ?? 0,
    operator: entry.operator,
    codes: entry.codes ?? [],
    failed: false,
    error: null,
    live: false
  };
}

/** Everything on screen, live first when the same job appears in both. */
export function merge(jobs: Job[], history: ProcessedDocument[]): Entry[] {
  const live = jobs.map(fromJob);
  const seen = new Set(jobs.map((job) => job.id));
  return [...live, ...history.filter((row) => !seen.has(row.job_id)).map(fromHistory)];
}

function since(period: Period): number {
  if (period === 'todo') return 0;
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  if (period === 'hoy') return start.getTime();
  if (period === 'semana') return start.getTime() - 6 * DAY;
  return start.getTime() - 29 * DAY;
}

/**
 * Whether a live entry matches the search.
 *
 * Name or resolution number, because "00086" is at least as likely a search as
 * a file name -- it is the number printed on the document itself.
 */
function matches(entry: Entry, needle: string): boolean {
  if (entry.name.toLowerCase().includes(needle)) return true;
  return entry.codes.some((code) => code.toLowerCase().includes(needle));
}

export function apply(entries: Entry[], filters: Filters): Entry[] {
  const needle = filters.text.trim().toLowerCase();
  const from = since(filters.period);

  return entries.filter((entry) => {
    // History arrives already narrowed by the service, which searches the whole
    // ledger -- every code and title, not the handful a card carries. Matching
    // it again here would drop rows the search legitimately found, which is
    // exactly how searching by resolution number came back empty.
    if (needle && entry.live && !matches(entry, needle)) return false;
    if (from && entry.at < from) return false;
    if (filters.operator !== 'todos' && (entry.operator ?? '') !== filters.operator) return false;
    if (filters.status === 'revision' && !entry.review) return false;
    if (filters.status === 'limpios' && (entry.review || entry.failed)) return false;
    if (filters.status === 'fallidos' && !entry.failed) return false;
    return true;
  });
}

export function order(entries: Entry[], sort: Sort): Entry[] {
  const sorted = [...entries];
  switch (sort) {
    case 'antiguo':
      return sorted.sort((a, b) => a.at - b.at);
    case 'resoluciones':
      return sorted.sort((a, b) => b.resolutions - a.resolutions || b.at - a.at);
    case 'paginas':
      return sorted.sort((a, b) => b.pages - a.pages || b.at - a.at);
    case 'nombre':
      return sorted.sort((a, b) => a.name.localeCompare(b.name, 'es') || b.at - a.at);
    default:
      return sorted.sort((a, b) => b.at - a.at);
  }
}

export interface Day {
  key: string;
  label: string;
  entries: Entry[];
  documents: number;
  resolutions: number;
  pages: number;
  bytes: number;
  review: number;
}

function dayKey(at: number): string {
  const date = new Date(at);
  const month = String(date.getMonth() + 1).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${String(date.getDate()).padStart(2, '0')}`;
}

function dayLabel(at: number): string {
  const today = Date.now();
  if (dayKey(at) === dayKey(today)) return 'Hoy';
  if (dayKey(at) === dayKey(today - DAY)) return 'Ayer';
  return new Date(at).toLocaleDateString('es', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric'
  });
}

/**
 * Group into days, each carrying its own totals.
 *
 * A day heading that only says the date makes the operator add up the cards
 * underneath it themselves. Carrying the totals is the difference between a
 * list and a report.
 */
export function byDay(entries: Entry[], sort: Sort): Day[] {
  const buckets = new Map<string, Day>();

  for (const entry of entries) {
    const key = dayKey(entry.at);
    let day = buckets.get(key);
    if (!day) {
      day = {
        key,
        label: dayLabel(entry.at),
        entries: [],
        documents: 0,
        resolutions: 0,
        pages: 0,
        bytes: 0,
        review: 0
      };
      buckets.set(key, day);
    }
    day.entries.push(entry);
    day.documents += 1;
    day.resolutions += entry.resolutions;
    day.pages += entry.pages;
    day.bytes += entry.bytes;
    day.review += entry.review;
  }

  const days = [...buckets.values()];
  for (const day of days) day.entries = order(day.entries, sort);
  // Days always run newest first; the sort orders within a day. An "oldest
  // first" list of days would put today at the bottom, which nobody wants.
  return days.sort((a, b) => (sort === 'antiguo' ? a.key.localeCompare(b.key) : b.key.localeCompare(a.key)));
}

/** Operators seen in the data, for the filter. */
export function operators(entries: Entry[]): string[] {
  return [...new Set(entries.map((entry) => entry.operator).filter((name): name is string => !!name))].sort(
    (a, b) => a.localeCompare(b, 'es')
  );
}


/**
 * La selección de la lista, como funciones puras sobre datos.
 *
 * Vive aquí y no en la pantalla por la misma razón que los filtros: se puede
 * probar sin dibujar nada, y las reglas que importan -- qué pasa cuando se
 * marca "todos" con un filtro puesto, qué queda seleccionado cuando la lista
 * cambia debajo -- son reglas, no detalles de presentación.
 */

/**
 * La selección, limpia de lo que ya no está en la lista.
 *
 * Es la regla que evita el accidente: si el operador marca veinte documentos,
 * cambia el filtro y pulsa eliminar, sólo se borra lo que sigue viendo. Una
 * selección que sobrevive a su propia lista es una forma de borrar a ciegas.
 */
export function visibleSelection(selected: Set<string>, entries: Entry[]): string[] {
  const present = new Set(entries.map((entry) => entry.jobId));
  const kept: string[] = [];
  for (const entry of entries) {
    if (selected.has(entry.jobId) && present.has(entry.jobId) && !kept.includes(entry.jobId)) {
      kept.push(entry.jobId);
    }
  }
  return kept;
}

/** Añadir o quitar uno, devolviendo una selección nueva. */
export function toggle(selected: Set<string>, jobId: string): Set<string> {
  const next = new Set(selected);
  if (next.has(jobId)) next.delete(jobId);
  else next.add(jobId);
  return next;
}

/**
 * Marcar o desmarcar todo lo que se está viendo.
 *
 * "Todo" es siempre lo visible y nunca el archivo entero: marcar por error
 * ochocientos documentos que no caben en la pantalla es exactamente el
 * accidente que este control no debe permitir.
 */
export function toggleAll(selected: Set<string>, entries: Entry[]): Set<string> {
  const visible = entries.map((entry) => entry.jobId);
  const todos = visible.length > 0 && visible.every((id) => selected.has(id));
  const next = new Set(selected);
  for (const id of visible) {
    if (todos) next.delete(id);
    else next.add(id);
  }
  return next;
}

/** Lo que se va a borrar, contado para poder decirlo antes de borrarlo. */
export function selectionTotals(
  selected: Set<string>,
  entries: Entry[]
): { documents: number; resolutions: number; pages: number } {
  let documents = 0;
  let resolutions = 0;
  let pages = 0;
  const contados = new Set<string>();
  for (const entry of entries) {
    if (!selected.has(entry.jobId) || contados.has(entry.jobId)) continue;
    contados.add(entry.jobId);
    documents += 1;
    resolutions += entry.resolutions;
    pages += entry.pages;
  }
  return { documents, resolutions, pages };
}
