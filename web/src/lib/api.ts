import type { OracleChoice } from './oracles';
import type {
  Batch,
  FuidStatus,
  JobState,
  TaskKind,
  FolderRun,
  InventoryPage,
  FolderListing,
  Job,
  InventoryRow,
  ProcessedDocument,
  SourceDisposition
} from './types';

const BASE = '/api';

export class ApiError extends Error {}

/**
 * Who to attribute new work to. Set by the session, read on every intake.
 *
 * Percent-encoded on the way out: HTTP header values are ASCII, and a name
 * with an accent -- Martínez, Muñoz, María -- throws in fetch before the
 * request leaves the browser.
 */
let operator: string | null = null;

export function setOperator(name: string | null): void {
  operator = name;
}

function attribution(): Record<string, string> {
  return operator ? { 'X-Operator': encodeURIComponent(operator) } : {};
}

async function detailOf(response: Response): Promise<string> {
  const payload = await response.json().catch(() => null);
  if (payload?.detail) return payload.detail;

  // A 404 or 405 on an endpoint this build knows about means the service
  // answering is older than the screen asking. That is a restart, not a bad
  // request, and saying so is the difference between a one-line fix and an
  // afternoon spent doubting the input.
  if (response.status === 404 || response.status === 405) {
    return (
      `El servicio no reconoce esta operación (${response.status}). ` +
      'Probablemente esté corriendo una versión anterior: reinicie el backend ' +
      '(uvicorn resolutions.api.main:app --port 8000) y vuelva a intentar.'
    );
  }
  return `Error ${response.status}`;
}

export async function createBatch(name: string): Promise<{ id: string; name: string }> {
  const response = await fetch(`${BASE}/batches`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name })
  });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

/**
 * Entrega un documento y dice qué hacer con él.
 *
 * `task` viaja en la consulta y no en el cuerpo porque el cuerpo es el archivo:
 * el servicio necesita saber qué se le pide antes de terminar de recibirlo, y
 * así puede rechazar una acción desconocida sin haber escrito nada en disco.
 */
export async function uploadDocument(
  file: File,
  batchId?: string,
  task: TaskKind = 'split',
  oracle: OracleChoice = 'auto'
): Promise<{ id: string }> {
  const body = new FormData();
  body.append('file', file);

  const query = new URLSearchParams();
  if (batchId) query.set('batch_id', batchId);
  if (task !== 'split') query.set('task', task);
  // El servicio rechaza con 422 un modelo sin llave, y lo hace antes de
  // recibir el archivo. No se manda 'auto' porque es el valor por omisión.
  if (oracle !== 'auto') query.set('oracle', oracle);
  const suffix = query.toString();

  const url = suffix ? `${BASE}/jobs?${suffix}` : `${BASE}/jobs`;
  const response = await fetch(url, { method: 'POST', body, headers: attribution() });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

export async function listJobs(): Promise<Job[]> {
  const response = await fetch(`${BASE}/jobs`);
  if (!response.ok) return [];
  return (await response.json()).jobs ?? [];
}

export async function listBatches(): Promise<Batch[]> {
  const response = await fetch(`${BASE}/batches`);
  if (!response.ok) return [];
  return (await response.json()).batches ?? [];
}

/**
 * Subscribe to job updates.
 *
 * The server pushes coalesced frames; the client never polls. Polling a queue of
 * long-running jobs is a request storm that says nothing new most of the time.
 */
export function streamEvents(handlers: {
  job: (job: Job) => void;
  folderRun?: (run: FolderRun) => void;
}): () => void {
  const events = new EventSource(`${BASE}/events`);
  events.onmessage = (event) => {
    try {
      const frame = JSON.parse(event.data);
      // Frames from before `kind` existed are jobs; that is the only default
      // that keeps an older service readable by a newer screen.
      if (frame?.kind === 'folder_run') handlers.folderRun?.(frame as FolderRun);
      else handlers.job(frame as Job);
    } catch {
      // A malformed frame is not worth tearing the stream down for.
    }
  };
  return () => events.close();
}

export function downloadUrl(jobId: string, name: string): string {
  return `${BASE}/jobs/${jobId}/outputs/${encodeURIComponent(name)}`;
}

/**
 * Run `task` over `items` with at most `limit` in flight.
 *
 * Fifty uploads fired at once only starve each other and blow up the browser's
 * connection pool; a small window keeps every transfer moving at full speed.
 */
export async function withConcurrency<T>(
  items: T[],
  limit: number,
  task: (item: T, index: number) => Promise<void>
): Promise<void> {
  let cursor = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor++;
      await task(items[index], index);
    }
  });
  await Promise.all(runners);
}

/**
 * Clear the screen: the API forgets every finished document.
 *
 * The generated PDFs and the inventory are untouched. Anything queued or
 * running is left alone, so this is safe to press mid-batch.
 */
export async function clearScreen(): Promise<{ removed: number }> {
  const response = await fetch(`${BASE}/jobs`, { method: 'DELETE' });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

/** Forget one document. With `purge`, its generated PDFs go too. */
export async function deleteJob(jobId: string, purge = false): Promise<void> {
  const url = `${BASE}/jobs/${jobId}${purge ? '?purge=true' : ''}`;
  const response = await fetch(url, { method: 'DELETE' });
  if (!response.ok) throw new ApiError(await detailOf(response));
}

export async function fetchInventory(
  query = '',
  limit = 500,
  offset = 0
): Promise<InventoryPage> {
  const parameters = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (query) parameters.set('q', query);
  const response = await fetch(`${BASE}/inventory?${parameters}`);
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

export async function fetchProcessedDocuments(
  query = '',
  limit = 500
): Promise<{ documents: ProcessedDocument[]; total: number }> {
  const parameters = new URLSearchParams({ limit: String(limit) });
  if (query) parameters.set('q', query);
  const response = await fetch(`${BASE}/documents?${parameters}`);
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

/**
 * El inventario completo como libro de Excel, con el filtro de la pantalla.
 *
 * Era un CSV, y un CSV lo abre Excel como texto crudo: sin anchos, sin bordes y
 * -- lo que de verdad estorba -- convirtiendo 00072 en 72, que es justo el dato
 * que hay que poder leer.
 */
export function inventoryUrl(query = ''): string {
  return query ? `${BASE}/inventory.xlsx?q=${encodeURIComponent(query)}` : `${BASE}/inventory.xlsx`;
}

/**
 * Cambiar el rumbo de un documento que ya está corriendo.
 *
 * La orden no es instantánea y no pretende serlo: el worker la atiende entre
 * una página y la siguiente, que es el único punto donde no hay nada a medio
 * escribir. Con OCR eso es alrededor de un segundo.
 */
export async function steerJob(
  jobId: string,
  action: 'pause' | 'resume' | 'cancel'
): Promise<{ state: JobState }> {
  const response = await fetch(`${BASE}/jobs/${jobId}/${action}`, { method: 'POST' });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

/** Lo mismo para un lote entero: pausar cincuenta de uno en uno no es una función. */
export async function steerBatch(
  batchId: string,
  action: 'pause' | 'resume' | 'cancel'
): Promise<{ jobs: string[] }> {
  const response = await fetch(`${BASE}/batches/${batchId}/${action}`, { method: 'POST' });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

/** La hoja de un solo documento, la misma que quedó junto a sus PDF. */
export function documentInventoryUrl(jobId: string): string {
  return `${BASE}/jobs/${jobId}/inventory.xlsx`;
}

/**
 * El FUID de un documento inventariado.
 *
 * Es la planilla oficial rellenada por el servicio, no una armada en el
 * navegador: lo que se descarga es el archivo que quedó escrito en disco.
 */
export function documentFuidUrl(jobId: string): string {
  return `${BASE}/jobs/${jobId}/fuid.xlsx`;
}

/**
 * Levantar el inventario de un documento que ya se procesó.
 *
 * Es la misma acción que «Solo inventariar» de la pantalla de carga -- el mismo
 * worker y la misma plantilla elegida por el tipo de documento que se reconozca
 * -- aplicada a algo que ya pasó por el sistema. Devuelve enseguida: leer un
 * libro de cuatrocientos folios son minutos, y el estado se consulta aparte.
 */
export async function makeDocumentFuid(jobId: string): Promise<FuidStatus> {
  const response = await fetch(`${BASE}/jobs/${jobId}/fuid`, {
    method: 'POST',
    headers: attribution()
  });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return { working: false, ...(await response.json()) };
}

/** Si ya está escrito. Se consulta mientras se levanta. */
export async function documentFuidStatus(jobId: string): Promise<FuidStatus> {
  const response = await fetch(`${BASE}/jobs/${jobId}/fuid`);
  if (!response.ok) throw new ApiError(await detailOf(response));
  return await response.json();
}

/**
 * The API revision this build of the screen needs.
 *
 * Raised alongside `API_REVISION` in the service whenever a screen starts
 * depending on a new endpoint. A service older than this is not broken, it is
 * stale, and saying which is the difference between a restart and a bug hunt.
 */
export const REQUIRED_API_REVISION = 14;

export interface Health {
  status: string;
  /** Absent on any service older than the revision scheme itself. */
  api_revision?: number;
  features?: string[];
  document_workers: number;
  page_workers: number;
  vision: 'claude' | 'disabled';
  /**
   * De cada modelo, si el servicio tiene llave para pedirlo.
   *
   * Opcional a propósito: un servicio anterior a la revisión 17 no lo
   * declara, y ahí no se sabe qué llaves hay. No saber no es lo mismo que
   * no haber, así que `oracles.ts` ofrece el automático y apaga el resto
   * diciendo por qué, en vez de adivinar.
   */
  oracles?: Record<OracleChoice, boolean>;
  queued: number;
  queue_limit: number;
}

/** One cheap call. Used by the status rail, which polls it slowly on purpose. */
export async function fetchHealth(): Promise<Health | null> {
  try {
    const response = await fetch(`${BASE}/health`);
    return response.ok ? await response.json() : null;
  } catch {
    // The rail reports "sin conexión" from a null; it never throws at the UI.
    return null;
  }
}


// -- mutations ---------------------------------------------------------------

async function send<T>(url: string, method: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: {
      ...attribution(),
      ...(body === undefined ? {} : { 'content-type': 'application/json' })
    },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

/** Correct a resolution's number, its title, or both. */
export function renameOutput(
  jobId: string,
  name: string,
  changes: { code?: string; title?: string | null }
): Promise<{ file_name: string; code: string; title: string | null }> {
  return send(`${BASE}/jobs/${jobId}/outputs/${encodeURIComponent(name)}`, 'PATCH', changes);
}

/** Delete one generated resolution: the file and its inventory row. */
export function deleteOutput(jobId: string, name: string): Promise<{ deleted: string }> {
  return send(`${BASE}/jobs/${jobId}/outputs/${encodeURIComponent(name)}`, 'DELETE');
}

/**
 * Rename a processed document, on screen and in the inventory at once.
 *
 * Distinct from `renameJob`, which only touches the card while it is still on
 * screen: this one reaches the record, so the new name survives a restart.
 */
export function renameDocument(
  jobId: string,
  sourceDocument: string
): Promise<{ job_id: string; source_document: string; rows: number }> {
  return send(`${BASE}/documents/${jobId}`, 'PATCH', { source_document: sourceDocument });
}

/**
 * Un documento ya procesado, tal como lo recuerda el inventario.
 *
 * Es lo que permite abrir la ficha de un documento que ya salió del área de
 * trabajo. Trae menos que el informe en memoria -- el reparto por peldaños y la
 * cinta de páginas no se guardan -- y lo que trae es lo que se produjo.
 */
export interface ArchivedDocument extends ProcessedDocument {
  rows: InventoryRow[];
  on_screen: boolean;
}

export async function fetchDocument(jobId: string): Promise<ArchivedDocument> {
  const response = await fetch(`${BASE}/documents/${jobId}`);
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

/** Erase a processed document: its PDFs, its inventory rows and its card. */
export function deleteDocument(
  jobId: string
): Promise<{ job_id: string; rows: number; from_screen: boolean }> {
  return send(`${BASE}/documents/${jobId}`, 'DELETE');
}

/** Lo que devolvió un borrado en lote: qué se borró y qué no, uno por uno. */
export interface BulkDeleteResult {
  deleted: { job_id: string; rows: number; from_screen: boolean }[];
  failed: { job_id: string; reason: string }[];
  rows: number;
}

/**
 * Borrar varios documentos de una vez.
 *
 * No es una transacción y el resultado no finge que lo sea: viene una fila por
 * documento, y la pantalla enseña las que fallaron con su motivo. Un documento
 * que todavía se está procesando se rechaza sin arrastrar a los demás.
 */
export function deleteDocuments(jobIds: string[]): Promise<BulkDeleteResult> {
  return send(`${BASE}/documents`, 'DELETE', { job_ids: jobIds });
}

export function renameJob(jobId: string, filename: string): Promise<Job> {
  return send(`${BASE}/jobs/${jobId}`, 'PATCH', { filename });
}

export function renameBatch(batchId: string, name: string): Promise<Batch> {
  return send(`${BASE}/batches/${batchId}`, 'PATCH', { name });
}

export function deleteBatch(batchId: string, purge = false): Promise<{ removed: number }> {
  return send(`${BASE}/batches/${batchId}${purge ? '?purge=true' : ''}`, 'DELETE');
}

// -- local folders -----------------------------------------------------------

export function startFolderRun(options: {
  source: string;
  destination: string;
  disposition?: SourceDisposition;
  watch?: boolean;
  /** Qué hacer con cada documento: la misma decisión que en una subida. */
  task?: TaskKind;
  /** Y a qué modelo preguntarle por los bordes dudosos. */
  oracle?: OracleChoice;
}): Promise<FolderRun> {
  return send(`${BASE}/folder-runs`, 'POST', options);
}

export function stopFolderRun(runId: string): Promise<FolderRun> {
  return send(`${BASE}/folder-runs/${runId}/stop`, 'POST');
}

/**
 * Quitar de la pantalla una carpeta que ya terminó.
 *
 * No es parar: una carpeta en marcha el servicio se niega a olvidarla, porque
 * dejaría el trabajo corriendo sin nadie que informara de él. Y no deshace
 * nada: lo entregado sigue en la carpeta de destino y el archivo conserva sus
 * filas.
 */
export function forgetFolderRun(runId: string): Promise<{ removed: number; ids: string[] }> {
  return send(`${BASE}/folder-runs/${runId}`, 'DELETE');
}

/** Quitar de golpe todas las carpetas terminadas, dejando las que siguen vivas. */
export function clearFolderRuns(): Promise<{ removed: number; ids: string[] }> {
  return send(`${BASE}/folder-runs`, 'DELETE');
}

/**
 * Lista las carpetas de una ruta.
 *
 * Lo pregunta el servicio y no el navegador porque un navegador no puede
 * entregar una ruta absoluta: ni el selector de carpetas ni `webkitdirectory`
 * la exponen. El servicio corre junto a las carpetas, así que la ruta que
 * devuelve es la real.
 */
export async function browseFolders(path: string | null): Promise<FolderListing> {
  const url = path ? `${BASE}/folders?path=${encodeURIComponent(path)}` : `${BASE}/folders`;
  const response = await fetch(url);
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

/**
 * Abre el explorador de carpetas de Windows y espera a que elijan.
 *
 * Lo abre el servicio, no el navegador: ninguna API web entrega una ruta
 * absoluta. Sólo tiene sentido mientras el servicio corra en la misma máquina
 * que la pantalla; cuando no puede, responde 501 y la pantalla cae en su propio
 * explorador.
 */
export async function pickFolderNatively(
  title: string,
  initial?: string
): Promise<{ path: string | null; cancelled: boolean }> {
  const response = await fetch(`${BASE}/folders/pick`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ title, initial: initial || null })
  });
  if (response.status === 501) throw new PickerUnavailable(await detailOf(response));
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

/** El servicio no puede abrir una ventana: hay que usar el explorador propio. */
export class PickerUnavailable extends Error {}

export async function listFolderRuns(): Promise<FolderRun[]> {
  const response = await fetch(`${BASE}/folder-runs`);
  if (!response.ok) return [];
  return (await response.json()).runs ?? [];
}
