import { unitFor } from './format';
import type { Consumo, Job } from './types';

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
  /**
   * Las unidades que salieron: los archivos cortados o, de un acta de
   * consejo, las actas inventariadas. Se llamaba sólo «resoluciones» y de una
   * carpeta de actas decía «10 resoluciones · archivos generados» sin haber
   * escrito un solo PDF.
   */
  resolutions: number;
  /** Cuántas de esas unidades son actas de consejo inventariadas. */
  actas: number;
  /** Cómo se llaman las unidades: singular y plural, en minúsculas. */
  unidad: [string, string];
  bytes: number;
  reviewItems: number;
  repairs: number;
  quarantine: number;
  escalated: number;
  /**
   * Caras que no hubo que leer porque pertenecían a la hoja anterior.
   *
   * No es un hueco ni un fallo: es lo que **se dejó de pagar**. Una vuelta no
   * nombra ningún archivo -- el nombre sale de la cara que abre -- ni abre fila
   * del inventario, así que leerla sería pagar por un dato que nadie va a
   * mirar. En un libro foliado hoja a hoja es la mitad del libro, y hasta ahora
   * no se veía en ninguna parte.
   */
  unread: number;
  /** Where each page's answer came from, keyed by rung. */
  provenance: Record<string, number>;
  /**
   * Lo que costó producir todo esto, sumado de los informes de cada documento.
   * `null` cuando ninguno gastó nada: una tanda leída con el motor local no
   * enseña un gasto en cero.
   */
  consumo: Consumo | null;

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

  /**
   * Lo que una carpeta dejó en su destino: de dónde salió, adónde fue, cuántos
   * archivos y, si eran actas, su Excel general para bajarlo desde aquí.
   */
  entregas: Entrega[];

  /**
   * Los PDF que dejó un libro de actas dividido, para bajarlos desde aquí.
   * Sin esto se escribían en el trabajo y el informe no los nombraba.
   */
  archivos: { jobId: string; ruta: string }[];

  /** Every resolution produced, in document order. */
  codes: { code: string; title: string | null; size: number; document: string }[];

  /** Only for a folder run. */
  destination?: string;
  delivered?: number;

  /** The units this report folds together. Only on a 'tanda'. */
  parts?: Completion[];
}

export interface Entrega {
  nombre: string;
  origen: string;
  destino: string;
  archivos: number;
  /** El id de la corrida, para bajar su inventario general de actas. */
  inventarioDe: string | null;
  inventario: string | null;
}

const UNIDAD_GENERICA: [string, string] = ['unidad documental', 'unidades documentales'];
const UNIDAD_ACTA: [string, string] = ['acta', 'actas'];

/** El nombre de lo que salió de un trabajo, como lo dice la consola. */
function unidadDe(job: Job): [string, string] {
  if (job.report?.inventario_actas?.length) return UNIDAD_ACTA;
  return [unitFor(job.report, 1), unitFor(job.report, 2)];
}

/** Un solo nombre si todos coinciden; si se mezclan, el genérico. */
function unidadComun(nombres: [string, string][]): [string, string] {
  if (!nombres.length) return UNIDAD_GENERICA;
  const [primero] = nombres;
  return nombres.every((nombre) => nombre[1] === primero[1]) ? primero : UNIDAD_GENERICA;
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
  let actas = 0;
  let reviewItems = 0;
  let repairs = 0;
  let quarantine = 0;
  let escalated = 0;
  let unread = 0;
  let consumo: Consumo | null = null;

  for (const job of jobs) {
    const report = job.report;
    if (!report) continue;
    pages += report.page_count;
    consumo = sumarConsumo(consumo, report.consumo ?? null);
    // Cada clave se lee con red. Un informe de inventario no traía ninguna de
    // éstas y tumbaba el resumen entero -- y con él el modal de cierre, que es
    // lo único que le dice al operador que el trabajo terminó bien. Un informe
    // guardado por una versión anterior tampoco tiene por qué traerlas.
    const actasDelJob = report.inventario_actas?.length ?? 0;
    resolutions += report.groups?.length || actasDelJob;
    actas += actasDelJob;
    reviewItems += report.review_queue?.length ?? 0;
    repairs += report.repairs?.length ?? 0;
    quarantine += report.quarantine?.length ?? 0;
    escalated += report.stats?.escalated ?? 0;
    unread += report.stats?.no_leidas?.length ?? 0;
    // Un acta no escribe estadística de lectura en su informe; la cinta del
    // trabajo sí la lleva, página por página, y es la misma verdad.
    const lectura = report.stats?.by_provenance ?? job.progress?.by_provenance ?? {};
    for (const [rung, count] of Object.entries(lectura)) {
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
    actas,
    unidad: unidadComun(jobs.filter((job) => job.report).map(unidadDe)),
    bytes: jobs.reduce((sum, job) => sum + (job.bytes ?? 0), 0),
    reviewItems,
    repairs,
    quarantine,
    escalated,
    unread,
    provenance,
    consumo,
    items: jobs.map((job) => ({
      jobId: job.id,
      filename: job.filename,
      state: job.state,
      pages: job.report?.page_count ?? 0,
      resolutions: job.report?.groups?.length || job.report?.inventario_actas?.length || 0,
      bytes: job.bytes ?? 0,
      review: job.report?.review_queue?.length ?? 0,
      error: job.error
    })),
    codes,
    entregas: [],
    archivos: jobs.flatMap((job) =>
      job.report?.dividido
        ? (job.report.outputs ?? []).map((ruta) => ({ jobId: job.id, ruta }))
        : []
    )
  };
}

/**
 * Lo que una tanda trae dentro, dicho con sus nombres.
 *
 * «2 unidades procesadas» no decía qué: «Carpeta UPD3859771 y 1 documento»
 * sí. Hasta dos carpetas o lotes se nombran; más, se cuentan.
 */
export function describir(parts: Completion[]): string {
  const de = (kind: Completion['kind']) => parts.filter((part) => part.kind === kind);
  const piezas: string[] = [];
  for (const [kind, uno, varios] of [
    ['carpeta', 'Carpeta', 'carpetas'],
    ['lote', 'Lote', 'lotes']
  ] as const) {
    const suyas = de(kind);
    if (suyas.length === 1) piezas.push(`${uno} ${suyas[0].title}`);
    else if (suyas.length === 2) piezas.push(`${uno}s ${suyas[0].title} y ${suyas[1].title}`);
    else if (suyas.length) piezas.push(`${suyas.length} ${varios}`);
  }
  const sueltos = de('documento').length;
  if (sueltos) piezas.push(`${sueltos} ${sueltos === 1 ? 'documento' : 'documentos'}`);
  if (!piezas.length) return `${parts.length} unidades procesadas`;
  const texto =
    piezas.length === 1 ? piezas[0] : `${piezas.slice(0, -1).join(', ')} y ${piezas.at(-1)}`;
  return texto.charAt(0).toUpperCase() + texto.slice(1);
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
  let consumo: Completion['consumo'] = null;
  for (const part of parts) {
    for (const [rung, count] of Object.entries(part.provenance)) {
      provenance[rung] = (provenance[rung] ?? 0) + count;
    }
    consumo = sumarConsumo(consumo, part.consumo);
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
    title: describir(parts),
    finishedAt,
    consumo,
    elapsedSeconds: Math.max(0, (finishedAt - startedAt) / 1000),
    operator: parts.find((part) => part.operator)?.operator ?? null,
    documents: add((part) => part.documents),
    failedDocuments: add((part) => part.failedDocuments),
    pages: add((part) => part.pages),
    resolutions: add((part) => part.resolutions),
    actas: add((part) => part.actas),
    unidad: unidadComun(parts.filter((part) => part.resolutions).map((part) => part.unidad)),
    bytes: add((part) => part.bytes),
    reviewItems: add((part) => part.reviewItems),
    repairs: add((part) => part.repairs),
    quarantine: add((part) => part.quarantine),
    escalated: add((part) => part.escalated),
    unread: add((part) => part.unread),
    provenance,
    items: parts.flatMap((part) => part.items),
    codes: parts.flatMap((part) => part.codes),
    entregas: parts.flatMap((part) => part.entregas),
    archivos: parts.flatMap((part) => part.archivos),
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

/**
 * Dos consumos, sumados unidad por unidad y proveedor por proveedor.
 *
 * Las páginas facturadas se suman con páginas y los tokens con tokens; nunca
 * entre sí. El dinero sólo se suma si las dos partes lo traen: mezclar un
 * documento con precio y otro sin él daría un total que parece completo y no
 * lo es.
 */
function sumarConsumo(a: Consumo | null, b: Consumo | null): Consumo | null {
  if (!a) return b;
  if (!b) return a;
  const proveedores: Consumo['proveedores'] = { ...a.proveedores };
  for (const [nombre, cuenta] of Object.entries(b.proveedores)) {
    const previa = proveedores[nombre];
    proveedores[nombre] = previa
      ? {
          peticiones: previa.peticiones + cuenta.peticiones,
          paginas_facturadas: previa.paginas_facturadas + cuenta.paginas_facturadas,
          tokens_entrada: previa.tokens_entrada + cuenta.tokens_entrada,
          tokens_salida: previa.tokens_salida + cuenta.tokens_salida,
          tokens_cache: previa.tokens_cache + cuenta.tokens_cache,
          rechazos: previa.rechazos + cuenta.rechazos,
          fallos: previa.fallos + cuenta.fallos
        }
      : { ...cuenta };
  }
  const coste =
    a.coste_estimado !== null && b.coste_estimado !== null
      ? a.coste_estimado + b.coste_estimado
      : null;
  return {
    proveedores,
    peticiones: a.peticiones + b.peticiones,
    paginas_facturadas: a.paginas_facturadas + b.paginas_facturadas,
    tokens_entrada: a.tokens_entrada + b.tokens_entrada,
    tokens_salida: a.tokens_salida + b.tokens_salida,
    tokens_cache: a.tokens_cache + b.tokens_cache,
    tokens: a.tokens + b.tokens,
    rechazos: a.rechazos + b.rechazos,
    fallos: a.fallos + b.fallos,
    coste_estimado: coste,
    moneda: a.moneda
  };
}
