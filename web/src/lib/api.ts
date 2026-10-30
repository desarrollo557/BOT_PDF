import type { AgruparChoice, CorteChoice } from './habilidades';
import type { LecturaChoice } from './lectura';
import type { TipoOption, TipoPedido } from './tipos';
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
  RetomarChoice,
  SourceDisposition,
  UsuarioApi,
  FuidTabla
} from './types';

const BASE = '/api';

export class ApiError extends Error {}

/**
 * La petición no llegó al servicio: está apagado, se reinicia o se cayó la red.
 *
 * Aparte de un rechazo porque piden cosas distintas: un rechazo se lee y se
 * corrige; esto se arregla encendiendo el servicio y volviendo a intentar, y
 * no debe, por ejemplo, cerrar la sesión de quien está trabajando.
 */
export class SinConexion extends ApiError {
  constructor() {
    super(
      'No se pudo hablar con el servicio: puede estar apagado o reiniciándose. ' +
        'Espere unos segundos y vuelva a intentar.'
    );
  }
}

/**
 * `fetch`, con la caída de la red convertida en un error que se entiende.
 *
 * Sin esto, un servicio apagado llega a la pantalla como «Failed to fetch» o
 * «NetworkError when attempting to fetch resource», según el navegador.
 */
async function alServicio(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (problema) {
    // Quien abortó la petición lo hizo a propósito; no es una caída.
    if (problema instanceof DOMException && problema.name === 'AbortError') throw problema;
    throw new SinConexion();
  }
}

/** Una carpeta de red que pide usuario y clave, como la describe el servicio. */
export interface PedidoDeCredenciales {
  recurso: string;
  mensaje: string;
  /** La cuenta con permiso en ese recurso, cuando el servicio la sabe. */
  usuario?: string;
}

/** Si la respuesta es la pregunta de usuario y clave de una carpeta de red. */
export function credencialesPedidas(payload: unknown): PedidoDeCredenciales | null {
  const detail = (payload as { detail?: unknown } | null)?.detail as
    | { codigo?: unknown; recurso?: unknown; mensaje?: unknown; usuario?: unknown }
    | undefined;
  if (!detail || typeof detail !== 'object' || detail.codigo !== 'credenciales_de_red') return null;
  const pedido: PedidoDeCredenciales = {
    recurso: String(detail.recurso ?? ''),
    mensaje: String(detail.mensaje ?? '')
  };
  if (typeof detail.usuario === 'string' && detail.usuario) pedido.usuario = detail.usuario;
  return pedido;
}

type Preguntador = (
  pedido: PedidoDeCredenciales
) => Promise<{ usuario: string; clave: string } | null>;

/** Quién le pregunta al operador: el cuadro de `CredencialesDeRed.svelte`. */
let preguntar: Preguntador | null = null;

export function alPedirCredenciales(preguntador: Preguntador | null): void {
  preguntar = preguntador;
}

/**
 * `fetch`, con la caída de la red convertida en un error que se entiende, y
 * con la carpeta de red que pide usuario y clave resuelta en el camino.
 *
 * Cuando el servicio contesta 401 con `credenciales_de_red`, se le pregunta al
 * operador, se entra con lo que escriba (`POST /api/red/conectar`) y se repite
 * la petición: quien llamó recibe la respuesta como si nada. Si la clave no
 * sirve, se vuelve a preguntar con el motivo; si cancela, recibe el 401 y lo
 * enseña como cualquier otro error.
 */
async function pedir(input: string, init?: RequestInit): Promise<Response> {
  const respuesta = await alServicio(input, init);
  if (respuesta.status !== 401 || !preguntar) return respuesta;
  const pedido = credencialesPedidas(await respuesta.clone().json().catch(() => null));
  if (!pedido) return respuesta;
  const entrada = await entrarUnaVez(pedido);
  if (entrada.conectado) return alServicio(input, init);
  return entrada.fallo ? entrada.fallo.clone() : respuesta;
}

type Entrada = { conectado: true } | { conectado: false; fallo: Response | null };

/**
 * Las entradas en curso, por recurso. Al escribir una ruta de red la pantalla
 * pide varias cosas a la vez -- reconocer la carpeta, el explorador -- y cada
 * una recibía su 401: compartían el cuadro, pero cada una mandaba su propio
 * `conectar`, que en el servicio cerraba la sesión de la otra, y el cuadro
 * volvía a salir (2026-10-28, «el inicio de sesión me sale más de una vez»).
 * Ahora la primera pregunta y conecta; las demás esperan esa misma entrada.
 */
const entrando = new Map<string, Promise<Entrada>>();

function entrarUnaVez(pedido: PedidoDeCredenciales): Promise<Entrada> {
  const llave = pedido.recurso.toLowerCase();
  let entrada = entrando.get(llave);
  if (!entrada) {
    entrada = entrarAlRecurso(pedido).finally(() => entrando.delete(llave));
    entrando.set(llave, entrada);
  }
  return entrada;
}

/** Pregunta hasta que se entra, se cancela o el servicio contesta otra cosa. */
async function entrarAlRecurso(primero: PedidoDeCredenciales): Promise<Entrada> {
  let pedido: PedidoDeCredenciales | null = primero;
  while (pedido && preguntar) {
    const cuenta = await preguntar(pedido);
    if (!cuenta) return { conectado: false, fallo: null };
    const conexion = await alServicio(`${BASE}/red/conectar`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ ruta: pedido.recurso, usuario: cuenta.usuario, clave: cuenta.clave })
    });
    if (conexion.ok) return { conectado: true };
    if (conexion.status !== 401) return { conectado: false, fallo: conexion };
    pedido = credencialesPedidas(await conexion.clone().json().catch(() => null));
    if (!pedido) return { conectado: false, fallo: conexion };
  }
  return { conectado: false, fallo: null };
}

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

/**
 * La cédula de quien entró, con la que el servicio averigua su perfil.
 *
 * Va aparte del nombre del operador porque contestan preguntas distintas: el
 * nombre es una etiqueta que viaja hasta el libro mayor y la cédula es lo que
 * el servicio busca entre las altas. Sin acentos ni espacios, así que no hace
 * falta codificarla.
 *
 * No es una credencial y el servicio no la trata como tal. Lo que decide con
 * ella -- si a este perfil se le deja bajar la planilla -- es una barrera de
 * uso, no de seguridad, y está escrito así allá también.
 */
let cedula: string | null = null;

export function setIdentidad(valor: string | null): void {
  cedula = valor;
}

function attribution(): Record<string, string> {
  return {
    ...(operator ? { 'X-Operator': encodeURIComponent(operator) } : {}),
    ...(cedula ? { 'X-Cedula': cedula } : {})
  };
}

async function detailOf(response: Response): Promise<string> {
  return mensajeDe(response.status, await response.json().catch(() => null));
}

/** Un error de validación tal como lo describe pydantic, por si el servicio no lo tradujo. */
interface ErrorDeCampo {
  loc?: (string | number)[];
  msg?: string;
}

/** De dónde viene el parámetro; útil para el programa, ruido para quien lee. */
const ORIGENES = ['query', 'body', 'path', 'header', 'cookie'];

/**
 * Lo que se le enseña al operador cuando el servicio contesta que no.
 *
 * `detail` suele ser una frase, y ésa se usa tal cual. Cuando es una lista
 * -- es como FastAPI describe un parámetro mal escrito si nadie lo tradujo --
 * se arma una frase con el nombre del campo y el motivo, porque una lista
 * metida en un `Error` sale en pantalla como «[object Object]», que es lo que
 * se veía por escribir una letra donde iba un número.
 */
export function mensajeDe(status: number, payload: unknown): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string' && detail) return detail;
  // La carpeta de red que pide usuario y clave, cuando no se dieron.
  const pedido = credencialesPedidas(payload);
  if (pedido) return pedido.mensaje || 'La carpeta de red pide usuario y clave.';
  if (Array.isArray(detail) && detail.length) {
    const frases = (detail as ErrorDeCampo[]).map((error) => {
      const campo = (error.loc ?? [])
        .filter((parte) => !ORIGENES.includes(String(parte)))
        .join('.');
      const motivo = error.msg || 'no es válido';
      return campo ? `El parámetro «${campo}»: ${motivo}` : motivo;
    });
    return `${frases.join('. ')}.`;
  }

  // A 404 or 405 on an endpoint this build knows about means the service
  // answering is older than the screen asking. That is a restart, not a bad
  // request, and saying so is the difference between a one-line fix and an
  // afternoon spent doubting the input.
  if (status === 404 || status === 405) {
    return (
      `El servicio no reconoce esta operación (${status}). ` +
      'Probablemente esté corriendo una versión anterior: reinicie el backend ' +
      '(uvicorn resolutions.api.main:app --port 8000) y vuelva a intentar.'
    );
  }
  return `Error ${status}`;
}

export async function createBatch(name: string): Promise<{ id: string; name: string }> {
  const response = await pedir(`${BASE}/batches`, {
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
  oracle: OracleChoice = 'auto',
  lectura: LecturaChoice = 'local',
  tipo: TipoPedido = 'auto',
  corte: CorteChoice = 'pagina',
  agrupar: AgruparChoice = 'documento',
  territorial = '',
  paralelo = 0,
  tipoDocumento?: string,
  acta?: string
): Promise<{ id: string }> {
  const body = new FormData();
  body.append('file', file);

  const query = new URLSearchParams();
  if (batchId) query.set('batch_id', batchId);
  if (task !== 'split') query.set('task', task);
  // El servicio rechaza con 422 un modelo sin llave, y lo hace antes de
  // recibir el archivo. No se manda 'auto' porque es el valor por omisión.
  if (oracle !== 'auto') query.set('oracle', oracle);
  // Y tampoco 'local', por lo mismo: es lo que el servicio hace sin que se lo
  // pidan, y mandarlo obligaría a los servicios viejos a entender un parámetro
  // que no conocen.
  if (lectura !== 'local') query.set('lectura', lectura);
  // Y el tipo declarado, por lo mismo: 'auto' es lo que el servicio hace sin
  // que se lo pidan.
  if (tipo !== 'auto') query.set('tipo', tipo);
  // Y el criterio con que se parte un libro de diplomas. 'pagina' es lo que el
  // servicio hace sin que se lo pidan, así que no viaja: mandarlo obligaría a
  // los servicios anteriores a esta revisión a entender un parámetro que no
  // conocen, y los haría contestar 422 a un trabajo que sabían hacer.
  if (corte !== 'pagina') query.set('corte', corte);
  // Y qué va en cada archivo de una caja de correspondencia. 'documento' es lo
  // de siempre y no viaja, por lo mismo que el corte.
  if (agrupar !== 'documento') query.set('agrupar', agrupar);
  // Y la territorial de una caja de correspondencia, para el encabezado de su
  // Índice Electrónico. Sólo viaja si se escribió.
  if (territorial.trim()) query.set('territorial', territorial.trim());
  // Y la plantilla del inventario, que sale del tipo de documento elegido
  // (índice electrónico, Kingspan o detección automática). Sólo viaja cuando se
  // eligió una; el servicio asume su comportamiento de siempre sin ella.
  if (tipoDocumento) query.set('tipo_documento', tipoDocumento);
  // Y cuántos archivos del lote a la vez. Cero es el automático y no viaja.
  if (paralelo > 0) query.set('paralelo', String(paralelo));
  // Y el acta de transferencia del inventario de Kingspan. Sólo viaja si se
  // eligió; el servicio rechaza una que no sea de su lista.
  if (acta) query.set('acta', acta);
  const suffix = query.toString();

  const url = suffix ? `${BASE}/jobs?${suffix}` : `${BASE}/jobs`;
  const response = await pedir(url, { method: 'POST', body, headers: attribution() });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

// Las tres listas que pintan la cola. Un error se dice: devolver `[]` dejaba
// la cola vacía y en silencio ante un 500, como si no hubiera nada.
export async function listJobs(): Promise<Job[]> {
  const response = await pedir(`${BASE}/jobs`);
  if (!response.ok) throw new ApiError(await detailOf(response));
  return (await response.json()).jobs ?? [];
}

export async function listBatches(): Promise<Batch[]> {
  const response = await pedir(`${BASE}/batches`);
  if (!response.ok) throw new ApiError(await detailOf(response));
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
  /** Si el flujo está abierto: el navegador reconecta solo, pero la pantalla tiene que saberlo. */
  conexion?: (abierta: boolean) => void;
}): () => void {
  const events = new EventSource(`${BASE}/events`);
  events.onopen = () => handlers.conexion?.(true);
  events.onerror = () => handlers.conexion?.(false);
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

/** Qué parece ser un PDF, según su patrón: el tipo, cómo se supo y por qué. */
export interface Sugerencia {
  tipo: string;
  etiqueta: string;
  /** «marcadores», «veto», «nucleo» o «nombre»; vacío si no se reconoció. */
  por: string;
  motivo: string;
  paginas: number;
}

/** Lo que hay en una carpeta local, PDF por PDF y contado por tipo. */
export interface SugerenciaDeCarpeta {
  ruta: string;
  /** Si se lee por la red: también «Z:\…» cuando esa unidad es de red. */
  de_red?: boolean;
  total: number;
  /** Falso si el conteo se paró en su tope: hay al menos `total`. */
  total_exacto?: boolean;
  mirados: number;
  por_tipo: { tipo: string; etiqueta: string; cantidad: number }[];
  archivos: (Sugerencia & { ruta: string })[];
  /**
   * La oficina productora que llevará la cabecera del FUID si el operador no
   * escribe otra: la del inventario del cliente que traiga la carpeta o la que
   * nombra la carpeta. Nula, la de la plantilla. Ausente en un servicio anterior.
   */
  oficina?: string | null;
}

/** Qué parece un PDF recién soltado. Sólo su capa de texto: no gasta nada. */
export async function reconocerArchivo(file: File, signal?: AbortSignal): Promise<Sugerencia> {
  const cuerpo = new FormData();
  cuerpo.append('file', file);
  const response = await pedir(`${BASE}/reconocer`, {
    method: 'POST',
    body: cuerpo,
    headers: attribution(),
    signal
  });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

/** Qué hay en una carpeta local y sus subcarpetas, antes de procesarla. */
export async function reconocerCarpeta(
  ruta: string,
  signal?: AbortSignal
): Promise<SugerenciaDeCarpeta> {
  const response = await pedir(`${BASE}/reconocer-carpeta`, {
    method: 'POST',
    body: JSON.stringify({ ruta }),
    headers: { 'Content-Type': 'application/json', ...attribution() },
    signal
  });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

/** Los PDF y el Excel que dejó un trabajo, tal como están en el disco. */
export interface ArchivosDelTrabajo {
  archivos: { ruta: string; nombre: string; bytes: number }[];
  inventario: string | null;
}

/** Todo lo que dejó un trabajo, sus PDF y su Excel, en un solo ZIP. */
export function archivosZipUrl(jobId: string): string {
  return `${BASE}/jobs/${jobId}/archivos.zip`;
}

export async function fetchArchivos(jobId: string): Promise<ArchivosDelTrabajo> {
  const response = await pedir(`${BASE}/jobs/${jobId}/archivos`, { headers: attribution() });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
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
  const response = await pedir(`${BASE}/jobs`, { method: 'DELETE' });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

/** Forget one document. With `purge`, its generated PDFs go too. */
export async function deleteJob(jobId: string, purge = false): Promise<void> {
  const url = `${BASE}/jobs/${jobId}${purge ? '?purge=true' : ''}`;
  const response = await pedir(url, { method: 'DELETE' });
  if (!response.ok) throw new ApiError(await detailOf(response));
}

export async function fetchInventory(
  query = '',
  limit = 500,
  offset = 0
): Promise<InventoryPage> {
  const parameters = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (query) parameters.set('q', query);
  const response = await pedir(`${BASE}/inventory?${parameters}`);
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

export async function fetchProcessedDocuments(
  query = '',
  limit = 500
): Promise<{ documents: ProcessedDocument[]; total: number }> {
  const parameters = new URLSearchParams({ limit: String(limit) });
  if (query) parameters.set('q', query);
  const response = await pedir(`${BASE}/documents?${parameters}`);
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
  const response = await pedir(`${BASE}/jobs/${jobId}/${action}`, { method: 'POST' });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

/** Lo mismo para un lote entero: pausar cincuenta de uno en uno no es una función. */
export async function steerBatch(
  batchId: string,
  action: 'pause' | 'resume' | 'cancel'
): Promise<{ jobs: string[] }> {
  const response = await pedir(`${BASE}/batches/${batchId}/${action}`, { method: 'POST' });
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

/** El inventario de las actas de una carpeta entera: una fila por PDF. */
export function folderInventarioUrl(runId: string): string {
  return `${BASE}/folder-runs/${runId}/inventario.xlsx`;
}

/**
 * El Excel general de una carpeta desde el Archivo. Sirve también cuando la
 * corrida ya no está en pantalla: el servicio lo busca donde quedó entregado.
 */
export function origenInventarioUrl(origenId: string): string {
  return `${BASE}/origenes/${encodeURIComponent(origenId)}/inventario.xlsx`;
}

/**
 * El inventario general del bot de un lote o una carpeta: una fila por PDF
 * procesado -- habilidad, lectura, páginas, documentos, revisión, estado --.
 * Es el mismo para cualquier habilidad; el de cada habilidad es el otro.
 */
export function origenProcesosUrl(origenId: string): string {
  return `${BASE}/origenes/${encodeURIComponent(origenId)}/procesos.xlsx`;
}

/**
 * Baja una planilla que el servicio sólo entrega a quien se identifica.
 *
 * No vale un enlace con `href`: el navegador lo sigue sin las cabeceras de esta
 * pantalla, el servicio no sabe quién lo pide y contesta 401 -- y lo que el
 * operador veía al pulsar «descargar el Excel» era una página con un error en
 * vez de su planilla. Así que se pide con `fetch`, que sí lleva la cédula, y lo
 * que vuelve se guarda como archivo con el nombre que dio el servicio.
 */
export async function descargarPlanilla(url: string, nombre = 'inventario.xlsx'): Promise<void> {
  const response = await pedir(url, { headers: attribution() });
  if (!response.ok) {
    throw Object.assign(new ApiError(await detailOf(response)), { status: response.status });
  }
  const archivo = nombreDeLaDescarga(response.headers.get('content-disposition')) ?? nombre;
  const enlace = document.createElement('a');
  enlace.href = URL.createObjectURL(await response.blob());
  enlace.download = archivo;
  document.body.appendChild(enlace);
  enlace.click();
  enlace.remove();
  // Después de que el navegador haya empezado a guardarlo, no antes.
  setTimeout(() => URL.revokeObjectURL(enlace.href), 10_000);
}

/** El nombre que trae `Content-Disposition`, en su forma UTF-8 si la trae. */
export function nombreDeLaDescarga(cabecera: string | null): string | null {
  if (!cabecera) return null;
  const utf8 = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(cabecera);
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1].trim().replace(/^"|"$/g, ''));
    } catch {
      // Mal codificado: se prueba con la forma simple.
    }
  }
  const simple = /filename="?([^";]+)"?/i.exec(cabecera);
  return simple ? simple[1].trim() : null;
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
  const response = await pedir(`${BASE}/jobs/${jobId}/fuid`, {
    method: 'POST',
    headers: attribution()
  });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return { working: false, ...(await response.json()) };
}

/** Si ya está escrito. Se consulta mientras se levanta. */
export async function documentFuidStatus(jobId: string): Promise<FuidStatus> {
  const response = await pedir(`${BASE}/jobs/${jobId}/fuid`);
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
export const REQUIRED_API_REVISION = 24;

export interface Health {
  status: string;
  /** Absent on any service older than the revision scheme itself. */
  api_revision?: number;
  features?: string[];
  document_workers: number;
  page_workers: number;
  /** Cuántos documentos de carpeta van a la vez en automático. */
  folder_documents?: number;
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
  /**
   * Con qué puede leer el papel este servicio. Ausente en cualquier servicio
   * anterior a esta revisión, y ahí vale lo mismo que con `oracles`: no saber
   * no es no haber, así que se ofrece el local y se apaga el resto diciendo
   * por qué.
   */
  readers?: Record<LecturaChoice, boolean>;
  /**
   * Si el servicio encuentra Tesseract. Sin él, «OCR + IA» paga cada página en
   * el motor remoto y «Solo OCR» sale vacío. Ausente en un servicio anterior.
   */
  tesseract?: boolean;
  /**
   * Qué clases de documento se pueden declarar al cargar. Las enumera el
   * servicio para que el front no tenga que mantener la misma lista en su
   * idioma. Ausente en un servicio anterior a esta revisión, y ahí sólo se
   * ofrece el automático.
   */
  document_types?: TipoOption[];
  queued: number;
  queue_limit: number;
}

/**
 * El rendimiento del equipo y del bot, en vivo (`GET /api/rendimiento`).
 *
 * En Docker «equipo» es lo que ve el contenedor: la máquina de Docker Desktop.
 * Lo que el servicio no puede medir llega como `null`.
 */
export interface Rendimiento {
  equipo: {
    cpu: number | null;
    nucleos: number | null;
    carga: number | null;
    memoria_usada: number | null;
    memoria_total: number | null;
  };
  bot: {
    memoria: number | null;
    procesos: number;
    documentos_en_curso: number;
    en_cola: number;
    paginas_por_minuto: number | null;
    documentos_por_minuto: number | null;
  };
}

/** `null` si el servicio no contesta o es anterior a la medición. */
export async function fetchRendimiento(): Promise<Rendimiento | null> {
  try {
    const response = await pedir(`${BASE}/rendimiento`);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

/** One cheap call. Used by the status rail, which polls it slowly on purpose. */
export async function fetchHealth(): Promise<Health | null> {
  try {
    const response = await pedir(`${BASE}/health`);
    return response.ok ? await response.json() : null;
  } catch {
    // The rail reports "sin conexión" from a null; it never throws at the UI.
    return null;
  }
}


// -- mutations ---------------------------------------------------------------

async function send<T>(url: string, method: string, body?: unknown): Promise<T> {
  const response = await pedir(url, {
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
  const response = await pedir(`${BASE}/documents/${jobId}`);
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
  /** Y con qué motor leer el papel de esta carpeta. */
  lectura?: LecturaChoice;
  /** Y por dónde partir cada libro de diplomas que traiga. */
  corte?: CorteChoice;
  /** Y qué va en cada archivo de una caja de correspondencia. */
  agrupar?: AgruparChoice;
  /** Y la territorial de sus cajas, para el encabezado del Índice Electrónico. */
  territorial?: string;
  /** Y la plantilla del inventario: Afinia, Kingspan o automática. */
  tipoDocumento?: string;
  /** Y el acta de transferencia del inventario de Kingspan. */
  acta?: string;
  /** Y la oficina productora de la cabecera del FUID. Ausente, la averigua el servicio. */
  oficina?: string;
  /** Y qué clase de documento trae, cuando el operador lo sabe. */
  tipo?: TipoPedido;
  /** Y si retoma una entrega anterior (sólo libros de diplomas). */
  retomar?: RetomarChoice;
  /** Y cuántos PDF a la vez. Ausente es el automático. */
  paralelo?: number;
}): Promise<FolderRun> {
  return send(`${BASE}/folder-runs`, 'POST', options);
}

export function stopFolderRun(runId: string): Promise<FolderRun> {
  return send(`${BASE}/folder-runs/${runId}/stop`, 'POST');
}

/** Cuántos archivos a la vez, con la carpeta en marcha; 0 vuelve al automático. */
export function cambiarParalelo(runId: string, paralelo: number): Promise<FolderRun> {
  return send(`${BASE}/folder-runs/${runId}/paralelo`, 'POST', { paralelo });
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
  const response = await pedir(url);
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
  const response = await pedir(`${BASE}/folders/pick`, {
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
  const response = await pedir(`${BASE}/folder-runs`);
  if (!response.ok) throw new ApiError(await detailOf(response));
  return (await response.json()).runs ?? [];
}

// -----------------------------------------------------------------------------
//  Entrar, y quién puede entrar
// -----------------------------------------------------------------------------

/**
 * Entrar con el usuario «siar», sin contraseña.
 *
 * El perfil lo contesta el servicio a partir del alta que hizo el
 * administrador; la pantalla no lo decide ni puede concedérselo. Sobre un
 * archivo recién instalado, el primero que entra queda de administrador y la
 * respuesta lo dice en `primer_administrador`.
 */
export async function entrar(usuario: string): Promise<UsuarioApi> {
  const response = await pedir(`${BASE}/sesion`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ usuario })
  });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return await response.json();
}

/**
 * El FUID de un documento como tabla, para mirarlo sin descargarlo.
 *
 * Lo ven los tres perfiles. Sale del archivo que hay en el disco y no de una
 * tabla armada en el navegador, por lo mismo que la descarga sirve el archivo
 * escrito: lo que se mira y lo que se firma tienen que ser el mismo documento.
 */
export async function fuidTabla(jobId: string): Promise<FuidTabla> {
  const response = await pedir(`${BASE}/jobs/${jobId}/fuid.tabla`, { headers: attribution() });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return await response.json();
}
