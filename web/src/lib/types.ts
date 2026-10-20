import type { LecturaChoice } from './lectura';
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
  /** El tipo documental con el nombre del catálogo («ACTA DE CONSEJO», …). */
  type?: string | null;
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
  /**
   * Las caras que no hizo falta leer porque pertenecen a la hoja anterior.
   *
   * Opcional porque sólo la produce la ruta de los libros de registro, y
   * porque un informe guardado por una versión anterior no la trae.
   */
  no_leidas?: number[];
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
/**
 * Lo que el trabajo le pidió a los proveedores de pago, en sus unidades.
 *
 * El OCR cobra por página procesada -- es él quien lleva la cuenta, y es lo
 * que se anota --; los modelos de chat cobran por token. No se suman entre sí
 * porque no son la misma cosa ni cuestan lo mismo. El dinero sólo aparece si
 * el operador configuró un precio: una cifra inventada sería la única de la
 * pantalla que no sale de una medida.
 */
export interface Consumo {
  proveedores: Record<
    string,
    {
      peticiones: number;
      paginas_facturadas: number;
      tokens_entrada: number;
      tokens_salida: number;
      tokens_cache: number;
      rechazos: number;
      fallos: number;
    }
  >;
  peticiones: number;
  paginas_facturadas: number;
  tokens_entrada: number;
  tokens_salida: number;
  tokens_cache: number;
  tokens: number;
  rechazos: number;
  fallos: number;
  coste_estimado: number | null;
  moneda: string;
}

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
  /**
   * Lo que el worker quiso decir del trabajo en una frase: que la caja se
   * agrupó por mes y cuántas páginas quedaron sin fecha, o que no encontró
   * ninguna y la entregó por documento. Estaba en el informe y no lo pintaba
   * ninguna pantalla.
   */
  notices?: string[];
  /** Qué se entregó como un archivo en una caja de correspondencia. */
  agrupar?: 'documento' | 'mes';
  validation?: Validation;
  issues?: Issue[];
  /** Nombre del FUID escrito, cuando la acción lo incluía. */
  fuid?: string;
  fuid_error?: string;
  /** El Excel sencillo que deja un acta de consejo, y su única fila. */
  inventario?: string;
  inventario_error?: string;
  inventario_actas?: FilaDeActa[];
  /** El Índice Electrónico que dejó una caja de correspondencia, si lo dejó. */
  indice_electronico?: string;
  /** Si el libro de actas se dividió en un PDF por sesión. */
  dividido?: boolean;
  /** Las sesiones del libro, con sus páginas y las piezas que traen. */
  sesiones?: {
    orden: number;
    nombre: string;
    desde: number;
    hasta: number;
    piezas: { tipo: string; nombre: string; desde: number; hasta: number }[];
  }[];
  /** Lo que costó producir este documento. Ausente en los informes anteriores. */
  consumo?: Consumo | null;
}

/** Una fila del inventario de actas de consejo: lo que se ve de cada PDF. */
export interface FilaDeActa {
  archivo: string;
  acta: string;
  fecha: string;
  folio_inicial: number | string;
  folio_final: number | string;
  folios: number;
  resumen: string;
  observaciones: string;
  /** La carpeta (UPD) del PDF, cuando viene de una corrida de carpeta. */
  carpeta?: string;
  /** Qué páginas del PDF son esta acta: en un libro, sólo las suyas. */
  pagina_inicial?: number;
  pagina_final?: number;
  /** Las piezas de la sesión con sus páginas, en una línea. */
  piezas?: string;
  numero?: string;
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
  /** Lo gastado hasta ahora con los proveedores de pago, según el último aviso del worker. */
  consumo?: Consumo | null;
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
  /** Salud operativa del trabajo: ok, slow, stalled, warning, done, failed. */
  health?: 'ok' | 'slow' | 'stalled' | 'warning' | 'done' | 'failed';
  /** Avisos relevantes para el operador, sin forzar un fallo del documento. */
  warnings?: string[];
}

/**
 * Lo que se le pidió al sistema que hiciera con el documento.
 *
 * `split` parte el PDF en uno por unidad documental, que es lo que hacía
 * siempre. `inventory` sólo lo lee y levanta su FUID, dejando el original
 * entero: es la única opción para un libro empastado, que no se desencuaderna.
 * `both` hace las dos cosas sobre una sola lectura.
 *
 * `inventory_file` también deja el original entero, pero la unidad documental
 * es el archivo: sale una sola fila con su asunto, sus fechas extremas y sus
 * folios. Se distingue de `inventory` en eso -- aquél saca una fila por registro
 * de dentro del libro -- y es lo que se usa cuando el PDF ya es un documento.
 */
export type TaskKind = 'split' | 'inventory' | 'both' | 'segment' | 'inventory_file';

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
  lectura?: LecturaChoice;
  /** La carpeta local o el lote del que salió. Nulo si se cargó suelto. */
  origen?: Origen | null;
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

export type RunState =
  | 'scanning'
  | 'processing'
  | 'watching'
  /** En pausa tras una racha de fallos, o esperando a que vuelva el origen: retoma sola. */
  | 'recovering'
  | 'done'
  | 'stopped'
  | 'failed';
export type SourceDisposition = 'leave' | 'move' | 'delete';

/**
 * Qué hacer con lo que ya está en el destino, en una carpeta de libros de
 * diplomas: procesar todo, retomar sólo lo que falta, o sólo revisarlo.
 */
export type RetomarChoice = 'no' | 'faltantes' | 'revisar' | 'todo';

/** Lo que hay de un PDF de origen en el destino, contado página a página. */
export interface ConciliacionDeLibro {
  estado: 'sin procesar' | 'incompleto' | 'completo';
  paginas_del_origen: number;
  entregadas: number;
  faltantes: number;
  /** «1-206, 210». */
  faltantes_rangos: string;
  repetidas: string;
  archivos: number;
  ajenos: string[];
  sin_partir: { archivo: string; paginas: number }[];
}

/** Un PDF de una carpeta retomada: qué había, qué se hizo y cómo quedó. */
export interface ControlDeLibro {
  pdf: string;
  carpeta: string;
  antes: ConciliacionDeLibro | null;
  accion: string;
  despues: ConciliacionDeLibro | null;
  observaciones: string;
}

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
  lectura?: LecturaChoice;
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
  /**
   * Todos los que se procesan ahora, en el orden en que se tomaron: la carpeta
   * lleva varios a la vez. Ausente en un servicio anterior, que sólo daba
   * `current`.
   */
  en_curso?: { job_id: string; nombre: string }[];
  /**
   * Los últimos documentos que la corrida creó, en el orden en que los tomó.
   * Sólo los últimos: con veinte mil PDF mandarlos todos en cada aviso eran
   * cientos de KB. El total va en `job_count`.
   */
  job_ids: string[];
  /** Cuántos documentos creó la corrida. Ausente en un servicio anterior. */
  job_count?: number;
  /**
   * Lo que sumaban los documentos que ya salieron del registro de la pantalla,
   * para que el panel de la carpeta no encoja sus cifras al sacarlos.
   */
  retirados?: {
    procedencias: Record<string, number>;
    revision: number;
    fallidas: number;
    consumo: Consumo | null;
  };
  /** Ya entregados por una corrida anterior sin constancia de entrega. */
  sin_constancia?: number;
  /** Los que tenían la entrega cortada o el origen cambiado y se rehicieron. */
  rehechos?: number;
  /** Los PDF cuya copia al destino no terminó (cuentan también como fallidos). */
  entregas_incompletas?: number;
  /** Lo que conviene saber de la corrida y no es el fallo de un documento. */
  avisos?: string[];
  /** Los que fallaron y salieron bien en una vuelta de reintento. */
  recuperados?: number;
  /** Los que fallaron y esperan la vuelta de reintento del final. */
  por_reintentar?: number;
  /** Cuántas veces se pausó por una racha de fallos. */
  pausas?: number;
  /** Cuántos PDF a la vez eligió el operador; ausente o null es el automático. */
  paralelo?: number | null;
  discovered: number;
  processed: number;
  bytes_total: number;
  pages_total: number;
  failed: number;
  delivered: number;
  resolutions: number;
  deliveries: Delivery[];
  /**
   * El Excel con las actas de consejo de la carpeta, por su nombre, cuando ya
   * está escrito: una fila por PDF. Ausente en un servicio anterior a la
   * revisión 20.
   */
  inventario?: string | null;
  /** Dónde quedó, en el disco del servicio. */
  inventario_ruta?: string | null;
  /** Cuántas actas lleva. */
  inventario_filas?: number;
  /** Por qué no se pudo escribir, si falló. */
  inventario_error?: string | null;
  /**
   * El control de calidad del inventario antes de entregarlo: filas completas,
   * completadas razonando con las vecinas y con algún dato que el papel no
   * trae o no deja leer, por dato. Ausente en un servicio anterior.
   */
  inventario_validacion?: {
    filas: number;
    completas: number;
    razonadas: number;
    pendientes: number;
    por_dato: Record<string, number>;
    /** Nombres que las lecturas de la hoja no confirmaron del todo. */
    nombres_dudosos?: number;
  } | null;
  /** Si la corrida retoma una entrega anterior. Ausente en un servicio anterior. */
  retomar?: RetomarChoice;
  /** Los PDF que ya estaban completos en el destino y no se volvieron a leer. */
  ya_entregados?: number;
  /** «00.CONTROL DE ENTREGA.xlsx», cuando ya se escribió. */
  control?: string | null;
  control_ruta?: string | null;
  controles?: ControlDeLibro[];
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
  /** Los tipos documentales que salieron de él. Ausente en servicios anteriores. */
  types?: string[];
  /** De qué carpeta o lote salió. Nulos si se cargó suelto o en servicios anteriores. */
  origen_id?: string | null;
  origen?: string | null;
  origen_tipo?: string | null;
  origen_inventario?: string | null;
  /** Si es una caja de correspondencia con su Índice Electrónico en disco. */
  indice?: boolean;
}

/**
 * De qué corrida salió un documento: la carpeta local o el lote que lo trajo.
 *
 * Es lo que reúne sus PDF en una sola tarjeta del Archivo, con el nombre de la
 * carpeta raíz y no el de uno de sus archivos.
 */
export interface Origen {
  id: string;
  nombre: string;
  tipo: 'carpeta' | 'lote' | string;
  /** Dónde queda el Excel general de una carpeta de actas. */
  inventario?: string | null;
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
  /** Subcarpetas que no se mandaron: el explorador enseña las primeras 500. */
  omitidas?: number;
}


/** Si el inventario de un documento está escrito, y si algo falló al levantarlo. */
export interface FuidStatus {
  ready: boolean;
  name: string | null;
  error: string | null;
  working: boolean;
}

/** Una persona dada de alta, tal como la describe el servicio. */
export interface UsuarioApi {
  cedula: string;
  correo: string;
  nombre: string;
  perfil: 'administrador' | 'tecnico' | 'calidad';
  perfil_label: string;
  /** Sólo en la respuesta de entrar, y sólo la primera vez del archivo. */
  primer_administrador?: boolean;
}

/**
 * El FUID de un documento leído del disco, para enseñarlo en pantalla.
 *
 * `descargable` lo contesta el servicio y no lo deduce la pantalla: la decisión
 * de qué perfil se lleva la planilla vive en un solo sitio, y aquí se obedece.
 */
export interface FuidTabla {
  archivo: string;
  oficina_productora: string;
  objeto: string;
  /** Un nombre por columna, con los dos niveles ya juntos. */
  columnas: string[];
  /** El nivel de arriba del formato, con cuántas columnas abarca cada uno. */
  grupos: { titulo: string; ancho: number }[];
  /** El nivel de abajo, vacío donde la columna no tiene dos niveles. */
  subcolumnas: string[];
  filas: string[][];
  total: number;
  descargable: boolean;
}
