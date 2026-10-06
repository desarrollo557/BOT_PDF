import type { Entry } from './components/ProcessedCard.svelte';
import type { Job, Origen, ProcessedDocument } from './types';

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

/** Cómo anota el servicio un acta de consejo en el inventario. */
export const TIPO_ACTA = 'ACTA DE CONSEJO';

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
    live: true,
    acta: Boolean(job.report?.inventario_actas?.length),
    origen: job.origen ?? null,
    tipos: [
      ...new Set(
        (job.report?.inventory?.items ?? [])
          .map((item) => item.type)
          .filter((tipo): tipo is string => !!tipo)
      )
    ]
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
    live: false,
    acta: (entry.types ?? []).includes(TIPO_ACTA),
    origen: entry.origen_id
      ? {
          id: entry.origen_id,
          nombre: entry.origen || entry.origen_id,
          tipo: entry.origen_tipo || 'carpeta',
          inventario: entry.origen_inventario ?? null
        }
      : null,
    tipos: entry.types ?? []
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
/** Sin tildes: el OCR las pone y las quita, y quien busca no las escribe dos veces. */
function plano(texto: string): string {
  return texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

/**
 * Si una tarjeta responde a lo que se escribió en el buscador.
 *
 * Por cualquier dato que la describa -- el PDF del que salió, los números que
 * produjo, quién lo procesó -- y exigiendo todas las palabras escritas, en
 * cualquiera de ellos. Es la misma regla que aplica el servicio sobre el libro
 * mayor, y tienen que ser la misma: si aquí se filtrara más estrecho, la
 * pantalla escondería filas que la búsqueda encontró.
 */
function matches(entry: Entry, needle: string): boolean {
  const heno = plano(
    [entry.name, entry.operator ?? '', entry.origen?.nombre ?? '', ...entry.codes].join(' ')
  );
  return plano(needle)
    .split(/\s+/)
    .filter(Boolean)
    .every((termino) => heno.includes(termino));
}

export function apply(entries: Entry[], filters: Filters): Entry[] {
  const needle = filters.text.trim();
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

/**
 * Los documentos de una misma carpeta local o de un mismo lote, juntos.
 *
 * Una corrida por carpeta procesa cada PDF como un trabajo propio, y el
 * Archivo los dibujaba sueltos: una «carpeta» por PDF con el nombre del
 * archivo donde el operador buscaba el de la carpeta raíz. Reunidos, la
 * carpeta es una tarjeta con su nombre y sus PDF dentro.
 */
export interface Grupo {
  key: string;
  origen: Origen;
  entries: Entry[];
  /** El más reciente: es cuando la carpeta terminó de procesarse. */
  at: number;
  resolutions: number;
  pages: number;
  bytes: number;
  review: number;
  failed: number;
  /** Si trae actas de consejo, que son las que dejan un Excel general. */
  acta: boolean;
  operators: string[];
  tipos: string[];
}

/** Lo que ocupa un sitio en la lista: un documento suelto o una carpeta entera. */
export type Item =
  | { kind: 'documento'; key: string; entry: Entry }
  | { kind: 'grupo'; key: string; grupo: Grupo };

function unicos<T>(valores: T[]): T[] {
  return [...new Set(valores)];
}

function grupoDe(origen: Origen, entries: Entry[]): Grupo {
  return {
    key: `origen:${origen.id}`,
    origen,
    entries: [...entries].sort((a, b) => a.name.localeCompare(b.name, 'es', { numeric: true })),
    at: Math.max(...entries.map((entry) => entry.at)),
    resolutions: entries.reduce((sum, entry) => sum + entry.resolutions, 0),
    pages: entries.reduce((sum, entry) => sum + entry.pages, 0),
    bytes: entries.reduce((sum, entry) => sum + entry.bytes, 0),
    review: entries.reduce((sum, entry) => sum + entry.review, 0),
    failed: entries.filter((entry) => entry.failed).length,
    acta: entries.some((entry) => entry.acta),
    operators: unicos(
      entries.map((entry) => entry.operator).filter((name): name is string => !!name)
    ),
    tipos: unicos(entries.flatMap((entry) => entry.tipos ?? []))
  };
}

/**
 * Reunir lo que vino de una misma carpeta o lote; lo cargado suelto queda solo.
 *
 * Los PDF de dentro van en orden natural (1N°…, 2N°…, 10N°…), que es el de la
 * carpeta y no el de cuándo terminó cada uno.
 */
export function reunir(entries: Entry[]): Item[] {
  const porOrigen = new Map<string, { origen: Origen; entries: Entry[] }>();
  const items: Item[] = [];
  for (const entry of entries) {
    if (!entry.origen) {
      items.push({ kind: 'documento', key: entry.key, entry });
      continue;
    }
    let grupo = porOrigen.get(entry.origen.id);
    if (!grupo) {
      grupo = { origen: entry.origen, entries: [] };
      porOrigen.set(entry.origen.id, grupo);
    }
    grupo.entries.push(entry);
  }
  for (const { origen, entries: suyos } of porOrigen.values()) {
    const grupo = grupoDe(origen, suyos);
    items.push({ kind: 'grupo', key: grupo.key, grupo });
  }
  return items;
}

/** Lo que el orden necesita saber de un sitio de la lista, sea cual sea. */
function medidas(item: Item): { at: number; resolutions: number; pages: number; name: string } {
  if (item.kind === 'grupo') {
    const { at, resolutions, pages, origen } = item.grupo;
    return { at, resolutions, pages, name: origen.nombre };
  }
  const { at, resolutions, pages, name } = item.entry;
  return { at, resolutions, pages, name };
}

export function orderItems(items: Item[], sort: Sort): Item[] {
  const m = medidas;
  const sorted = [...items];
  switch (sort) {
    case 'antiguo':
      return sorted.sort((a, b) => m(a).at - m(b).at);
    case 'resoluciones':
      return sorted.sort((a, b) => m(b).resolutions - m(a).resolutions || m(b).at - m(a).at);
    case 'paginas':
      return sorted.sort((a, b) => m(b).pages - m(a).pages || m(b).at - m(a).at);
    case 'nombre':
      return sorted.sort(
        (a, b) => m(a).name.localeCompare(m(b).name, 'es', { numeric: true }) || m(b).at - m(a).at
      );
    default:
      return sorted.sort((a, b) => m(b).at - m(a).at);
  }
}

/**
 * Cómo se llaman las unidades que salieron, según qué papel era.
 *
 * La pantalla decía «resoluciones» de todo, y de un libro de actas salen
 * actas y de una caja de correspondencia, documentos.
 */
export function unidades(tipos: string[], acta = false): string {
  if (acta) return 'Actas';
  if (!tipos.length || tipos.every((tipo) => plano(tipo).startsWith('resolucion'))) {
    return 'Resoluciones';
  }
  return 'Documentos';
}

export interface Day {
  key: string;
  label: string;
  /** Los documentos del día, uno por uno, para contarlos y seleccionarlos. */
  entries: Entry[];
  /** Lo que se dibuja: documentos sueltos y carpetas enteras. */
  items: Item[];
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
 *
 * Una carpeta va entera en el día en que terminó, aunque haya empezado la
 * víspera: partirla en dos días la volvería a dejar como PDF sueltos.
 */
export function byDay(entries: Entry[], sort: Sort): Day[] {
  const buckets = new Map<string, Day>();

  for (const item of reunir(entries)) {
    const at = medidas(item).at;
    const key = dayKey(at);
    let day = buckets.get(key);
    if (!day) {
      day = {
        key,
        label: dayLabel(at),
        entries: [],
        items: [],
        documents: 0,
        resolutions: 0,
        pages: 0,
        bytes: 0,
        review: 0
      };
      buckets.set(key, day);
    }
    day.items.push(item);
    for (const entry of item.kind === 'grupo' ? item.grupo.entries : [item.entry]) {
      day.entries.push(entry);
      day.documents += 1;
      day.resolutions += entry.resolutions;
      day.pages += entry.pages;
      day.bytes += entry.bytes;
      day.review += entry.review;
    }
  }

  const days = [...buckets.values()];
  for (const day of days) {
    day.entries = order(day.entries, sort);
    day.items = orderItems(day.items, sort);
  }
  // Days always run newest first; the sort orders within a day. An "oldest
  // first" list of days would put today at the bottom, which nobody wants.
  return days.sort((a, b) =>
    sort === 'antiguo' ? a.key.localeCompare(b.key) : b.key.localeCompare(a.key)
  );
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
 * Marcar o desmarcar una carpeta entera: si ya estaban todos, se quitan; si
 * faltaba alguno, se marcan todos. Es la casilla de la tarjeta de la carpeta.
 */
export function toggleMany(selected: Set<string>, jobIds: string[]): Set<string> {
  const todos = jobIds.length > 0 && jobIds.every((id) => selected.has(id));
  const next = new Set(selected);
  for (const id of jobIds) {
    if (todos) next.delete(id);
    else next.add(id);
  }
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
