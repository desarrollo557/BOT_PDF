import type { OracleChoice } from './oracles';

export type JobState = 'queued' | 'running' | 'paused' | 'done' | 'failed' | 'cancelled';

export interface Group {
  code: string;
  title: string | null;
  pages: number[];
  size: number;
  /**
   * Qué clase de papel resultó ser, con el nombre del catálogo del archivo.
   * Sólo lo traen los documentos cortados de una caja, y vale "DOCUMENTO"
   * cuando el papel no dijo qué era: sin tipo es mejor que con el de al lado.
   */
  type?: string | null;
  /**
   * La fecha más reciente escrita en el documento, en ISO. Es la que lo fecha
   * -- la fecha extrema final del FUID -- y se lee de sus páginas, porque
   * estos papeles son escaneos y no traen metadatos.
   */
  fecha?: string | null;
}

export interface Repair {
  page: number;
  observed: string;
  applied: string;
  distance: number;
}

export interface ReviewItem {
  page: number;
  reason: string;
}

export interface InventoryItem {
  file_name: string;
  code: string;
  title: string | null;
  page_count: number;
  first_page: number;
  last_page: number;
  page_numbers: number[];
}

export interface Inventory {
  source_document: string;
  source_pages: number;
  generated_files: number;
  pages_accounted_for: number;
  items: InventoryItem[];
  quarantine_pages: number[];
  review_pages: number[];
}

export type DocumentTypeId = 'resolucion' | 'diploma' | 'matricula' | 'desconocido';

export interface Stats {
  by_provenance: Record<string, number>;
  escalated: number;
  vision_requests: number;
  resolved_by_context: number;
  vision_page_ratio: number;
  failed_pages: Record<string, string>;
  /** Páginas que declaran un número y se releyeron con OCR para contrastarlas. */
  verified?: number;
  /** Página → las dos lecturas que no coincidieron. */
  disagreements?: Record<string, string>;
  /** Qué resultó ser el documento, decidido sobre lo que se leyó de él. */
  document_type?: DocumentTypeId;
  type_confidence?: number;
}

/** Una cosa que no cuadra en la lectura, con el sitio exacto donde no cuadra. */
export interface Issue {
  field: string;
  reason: string;
  severity: 'error' | 'aviso';
  page: number | null;
  observed: string | null;
}

/** El recuento de la comprobación, para no tener que contar en la pantalla. */
export interface Validation {
  total: number;
  errores: number;
  avisos: number;
  por_campo: Record<string, number>;
  paginas: number[];
}

/**
 * Lo que devuelve un trabajo terminado.
 *
 * Los tres tipos de documento producen el mismo informe, pero no todos llenan
 * las mismas casillas: un libro de folios no tiene cuarentena porque ninguna
 * página hereda de otra, y un inventario no escribe salidas. Por eso todo lo
 * que puede faltar se declara opcional -- lo era de hecho desde que existen los
 * libros de diplomas, y no decirlo hacía que la pantalla se rompiera al
 * terminar uno en vez de fallar al compilar.
 */
export interface Report {
  document: string;
  page_count: number;
  groups?: Group[];
  quarantine?: number[];
  repairs?: Repair[];
  review_queue?: ReviewItem[];
  outputs?: string[];
  stats?: Stats;
  inventory?: Inventory | null;
  /** Qué resultó ser el documento. Ausente en los informes anteriores al tipo. */
  document_type?: DocumentTypeId;
  document_type_label?: string;
  type_confidence?: number;
  /** Cuántas filas tiene el inventario levantado, cuando se levantó uno. */
  records?: number;
  /** Presente en los informes nuevos; los guardados antes no lo traen. */
  task?: TaskKind;
  validation?: Validation;
  issues?: Issue[];
  /** Nombre del FUID escrito, cuando la acción lo incluía. */
  fuid?: string;
  fuid_error?: string;
}

/** Lo que devuelve un trabajo de inventario, que no escribe ningún PDF. */
export interface InventoryReport {
  document: string;
  page_count: number;
  task: 'inventory';
  /** Qué resultó ser el documento, decidido por lo que está impreso en él. */
  document_type: 'resolucion' | 'diploma' | 'matricula' | 'desconocido';
  document_type_label: string;
  type_confidence: number;
  /** Cuántas filas tiene el inventario. */
  records: number;
  /** Nombre del Excel escrito, ausente si no se pudo escribir. */
  fuid?: string;
  fuid_error?: string;
  validation: Validation;
  issues: Issue[];
  incidents: string[];
}

/** Live state of one document while it is being processed. */
export interface Progress {
  stage:
    | 'queued'
    | 'analysing'
    | 'identifying'
    | 'verifying'
    | 'grouping'
    | 'assembling'
    | 'inventorying'
    | 'delivering'
    | 'done'
    | 'failed';
  page_count: number;
  pages_done: number;
  failed_pages: number;
  by_provenance: Record<string, number>;
  /**
   * Por qué hay que mirar cada página marcada, indexado por número de página.
   *
   * Una página marcada casi nunca es una página ilegible: es una que se leyó y
   * cuyo contenido no se sostiene -- el folio del encabezado que no coincide
   * con el del pie, un nombre que no se pudo aislar. Sin este motivo la
   * pantalla sólo puede decir que algo pasa, y quien mira tiene que abrir el
   * documento para averiguar qué.
   *
   * Ausente en cualquier servicio anterior a que esto existiera.
   */
  review?: Record<string, string>;
  /** One character per page: . pending, t text, h header OCR, f full OCR, v model, x needs review. */
  ribbon: string;
  percent: number;
  pages_per_second: number;
  elapsed_seconds: number;
  /**
   * Qué está haciendo ahora mismo, en palabras.
   *
   * La etapa sola dice lo mismo en el archivo 1 que en el 287. Esto dice cuál,
   * y es lo que convierte "Escribiendo los PDF" en una frase que responde a
   * "¿por qué tarda?". Ausente en cualquier servicio anterior a que existiera.
   */
  detail?: string | null;
  /** Cuánto lleva hecho la etapa actual y de cuánto. No siempre son páginas. */
  stage_done?: number;
  stage_total?: number;
  /** Cuánto lleva en la etapa actual. Es la cifra que explica una espera. */
  stage_elapsed_seconds?: number;
  /** Cuánto hace que no llega noticia del worker. */
  silent_seconds?: number;
}

/**
 * Lo que se le pidió al sistema que hiciera con el documento.
 *
 * `split` parte el PDF en uno por unidad documental, que es lo que hacía
 * siempre. `inventory` sólo lo lee y levanta su FUID, dejando el original
 * entero: es la única opción para un libro empastado, que no se desencuaderna.
 * `both` hace las dos cosas sobre una sola lectura.
 */
export type TaskKind = 'split' | 'inventory' | 'both' | 'segment';

export interface Job {
  id: string;
  /** Set on the frame that announces the job was cleared from the workspace. */
  deleted?: boolean;
  batch_id: string | null;
  filename: string;
  /** Size of the source PDF, recorded at intake. */
  bytes: number;
  /** Who was at the console. Attribution, never authorisation. */
  operator: string | null;
  /** Qué se pidió hacer con él. Decidido al cargarlo. */
  task: TaskKind;
  /** A qué modelo se le pidió juzgar los bordes dudosos de esta caja. */
  oracle?: OracleChoice;
  state: JobState;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  report: Report | null;
  progress: Progress;
}

export interface Batch {
  id: string;
  name: string;
  created_at: string;
  documents: number;
  done: number;
  failed: number;
  running: number;
  paused: number;
  cancelled: number;
  queued: number;
  pages_total: number;
  pages_done: number;
  bytes_total: number;
  percent: number;
  resolutions: number;
  review_items: number;
  job_ids: string[];
}

/** One generated resolution PDF, as the durable inventory recorded it. */
export interface InventoryRow {
  recorded_at: string;
  source_document: string;
  code: string;
  title: string | null;
  /**
   * Qué clase de papel es, con el nombre del catálogo del archivo. Lo pone la
   * clasificación, que corre después del corte; nulo cuando nadie lo
   * reconoció, y nulo a propósito -- sin tipo es mejor que con el de al lado.
   */
  type?: string | null;
  /** La fecha del documento, leída de sus páginas. */
  fecha?: string | null;
  file_name: string;
  page_count: number;
  first_page: number;
  last_page: number;
  pages: string;
  /** Cuáles de esas páginas entraron como anexo, en rangos: "4-7". */
  attachments?: string;
  job_id: string;
  operator: string | null;
}

export interface InventorySummary {
  resolutions: number;
  documents: number;
  codes: number;
  pages: number;
}

export interface InventoryPage {
  rows: InventoryRow[];
  total: number;
  offset: number;
  limit: number;
  summary: InventorySummary;
}

export type RunState = 'scanning' | 'processing' | 'watching' | 'done' | 'stopped' | 'failed';
export type SourceDisposition = 'leave' | 'move' | 'delete';

/** One generated PDF copied into the destination folder. */
export interface Delivery {
  file_name: string;
  source_document: string;
  destination: string;
  at: string;
}

/** A local source folder being drained into a local destination folder. */
export interface FolderRun {
  kind: 'folder_run';
  id: string;
  source: string;
  destination: string;
  disposition: SourceDisposition;
  watch: boolean;
  /** Qué se le pidió hacer a cada documento de la carpeta. */
  task?: TaskKind;
  /** Y a qué modelo se le preguntó por los bordes dudosos. */
  oracle?: OracleChoice;
  operator: string | null;
  state: RunState;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  /** Los primeros de la cola, no todos: una carpeta real trae catorce mil. */
  queue: string[];
  /** Cuántos esperan de verdad, contados en el servicio. */
  queued?: number;
  current: string | null;
  current_job_id: string | null;
  /** Every document the run created, in the order it took them. */
  job_ids: string[];
  discovered: number;
  processed: number;
  bytes_total: number;
  pages_total: number;
  failed: number;
  delivered: number;
  resolutions: number;
  deliveries: Delivery[];
}

/** One source document ever processed, folded back out of the ledger. */
export interface ProcessedDocument {
  job_id: string;
  source_document: string;
  processed_at: string;
  resolutions: number;
  pages: number;
  codes: string[];
  operator: string | null;
  /** Facts about the source document, recorded alongside its resolutions. */
  source_pages: number;
  bytes: number;
  review: number;
}

/** Una carpeta, tal como la lista el explorador del servicio. */
export interface FolderEntry {
  name: string;
  path: string;
}

export interface FolderListing {
  path: string | null;
  parent: string | null;
  drives: FolderEntry[];
  folders: FolderEntry[];
}


/** Si el inventario de un documento está escrito, y si algo falló al levantarlo. */
export interface FuidStatus {
  ready: boolean;
  name: string | null;
  error: string | null;
  working: boolean;
}
