import {
  clearScreen,
  deleteJob,
  listBatches,
  listFolderRuns,
  listJobs,
  startFolderRun,
  clearFolderRuns,
  forgetFolderRun,
  stopFolderRun,
  streamEvents
} from './api';
import { consoleLog } from './console.svelte';
import type { FolderRun, Job, SourceDisposition, TaskKind } from './types';

/**
 * The live workspace, shared by every route.
 *
 * It lives here rather than in a page component because the detail view is a
 * route of its own: state owned by the workspace page would be torn down on
 * navigation, taking the event stream with it and reconnecting on the way back.
 * One connection, opened by the layout, outlives every route change.
 */
/**
 * Lo terminado que todavía puede necesitar un ojo humano.
 *
 * Un documento que falló, porque su error sólo está en su ficha, y uno que dejó
 * páginas marcadas, porque el motivo de cada una sólo está en su informe. Es lo
 * que hay que conservar cuando la pantalla se limpia.
 */
export function pendingReview(jobs: Job[]): Job[] {
  return jobs.filter(
    (job) => job.state === 'failed' || (job.report?.review_queue?.length ?? 0) > 0
  );
}

/**
 * Lo que ve la página de Revisión: lo que sigue en pantalla y lo que se apartó
 * de ella sin atender, sin repetir y con la versión viva por delante.
 */
export function mergeReviewable(finished: Job[], dismissed: Job[]): Job[] {
  const ids = new Set(finished.map((job) => job.id));
  return [...finished, ...dismissed.filter((job) => !ids.has(job.id))];
}

class JobStore {
  jobs = $state<Job[]>([]);
  runs = $state<FolderRun[]>([]);
  /**
   * Trabajos que salieron de la pantalla pero cuyo detalle todavía hace falta.
   *
   * Limpiar la pantalla olvida los trabajos en el servicio, y con ellos se iría
   * la lista de páginas por revisar -- que sólo existe dentro del informe de
   * cada documento. Como la pantalla es lo que se limpia y la revisión es lo
   * que queda pendiente, el navegador se queda una copia de lo que necesita
   * Revisión hasta que alguien la atienda.
   *
   * No es un duplicado del archivo: el archivo guarda qué se produjo, esto
   * guarda qué falta por mirar, que es una pregunta distinta y de vida más
   * corta.
   */
  dismissed = $state<Job[]>([]);
  /**
   * Sube cada vez que la mesa de trabajo vuelve a cero.
   *
   * Limpiar la pantalla borra lo que dibuja esta capa, pero no lo que el
   * operador dejó escrito en los formularios -- las rutas de origen y destino
   * de una carpeta, sobre todo -- y esas rutas encima de una pantalla vacía se
   * leen como si la carpeta siguiera en marcha.
   *
   * Es un contador y no un booleano porque lo que interesa es el momento en que
   * cambia, no el valor: dos reinicios seguidos son dos avisos, y un booleano
   * que ya estaba en `true` no avisaría del segundo.
   */
  resetSignal = $state(0);
  batchNames = $state<Record<string, string>>({});
  connected = $state(false);
  clearing = $state(false);

  #close: (() => void) | null = null;
  #refs = 0;

  get(id: string): Job | undefined {
    return this.jobs.find((job) => job.id === id);
  }

  /** Documents that finished, newest first. These are the folders on screen. */
  get finished(): Job[] {
    return this.jobs.filter(
      (job) => job.state === 'done' || job.state === 'failed' || job.state === 'cancelled'
    );
  }

  /**
   * Todo lo terminado que todavía puede necesitar un ojo: lo que sigue en
   * pantalla y lo que se apartó de ella sin atender.
   *
   * Es lo que lee la página de Revisión, y por eso limpiar la pantalla ya no le
   * quita nada. Los repetidos se resuelven a favor de lo que hay en pantalla,
   * que es la versión viva.
   */
  get reviewable(): Job[] {
    return mergeReviewable(this.finished, this.dismissed);
  }

  /**
   * Devolver la mesa de trabajo a su estado inicial.
   *
   * Lo llama quien sabe que la tanda terminó de verdad -- el informe al
   * cerrarse -- y no esta capa, que no puede distinguir una carpeta que acabó
   * de una que sigue vigilando.
   */
  resetWorkspace(): void {
    this.resetSignal += 1;
  }

  /** Quitar de la lista de pendientes lo que ya se atendió. */
  forget(jobId: string): void {
    this.dismissed = this.dismissed.filter((job) => job.id !== jobId);
  }

  /** Documents still queued or running. These keep their live card. */
  get inFlight(): Job[] {
    return this.jobs.filter(
      (job) => job.state === 'queued' || job.state === 'running' || job.state === 'paused'
    );
  }

  nameBatch(id: string, name: string): void {
    this.batchNames = { ...this.batchNames, [id]: name };
  }

  /**
   * Open the stream, ref-counted so a second caller does not open a second one.
   * Returns the matching release.
   */
  connect(): () => void {
    this.#refs += 1;
    if (this.#refs === 1) this.#open();
    return () => {
      this.#refs -= 1;
      if (this.#refs === 0) {
        this.#close?.();
        this.#close = null;
        this.connected = false;
      }
    };
  }

  #open(): void {
    consoleLog.push('SYS', 'conectando al flujo de eventos…', 'sys');
    listJobs().then((initial) => {
      this.jobs = initial;
      for (const job of initial) consoleLog.ingest(job);
    });
    listBatches().then((batches) => {
      // Names come from the API rather than from whoever happened to upload, so
      // a reload or a second tab labels the same batches the same way.
      this.batchNames = Object.fromEntries(batches.map((batch) => [batch.id, batch.name]));
    });
    // The stream replays current state on connect, so a reconnect after a
    // dropped socket resynchronises without any extra request.
    listFolderRuns().then((runs) => (this.runs = runs));
    this.#close = streamEvents({
      job: (job) => this.#upsert(job),
      folderRun: (run) => this.#upsertRun(run)
    });
    this.connected = true;
  }

  #upsert(incoming: Job): void {
    if (incoming.deleted) {
      // Another tab cleared it, or this one did. Either way it is gone.
      this.jobs = this.jobs.filter((job) => job.id !== incoming.id);
      return;
    }
    consoleLog.ingest(incoming);
    const index = this.jobs.findIndex((job) => job.id === incoming.id);
    if (index === -1) this.jobs = [incoming, ...this.jobs];
    else this.jobs[index] = incoming;
  }

  #upsertRun(incoming: FolderRun): void {
    const index = this.runs.findIndex((run) => run.id === incoming.id);
    if (index === -1) this.runs = [incoming, ...this.runs];
    else this.runs[index] = incoming;
  }

  /** Folder runs still consuming or watching a folder. */
  get activeRuns(): FolderRun[] {
    return this.runs.filter(
      (run) => run.state === 'scanning' || run.state === 'processing' || run.state === 'watching'
    );
  }

  async startFolder(options: {
    source: string;
    destination: string;
    disposition?: SourceDisposition;
    watch?: boolean;
    /** Qué hacer con cada documento: la misma decisión que en una subida. */
    task?: TaskKind;
  }): Promise<FolderRun> {
    const run = await startFolderRun(options);
    this.#upsertRun(run);
    consoleLog.push('DIR', `consumiendo ${run.source}`, 'net');
    return run;
  }

  async stopFolder(runId: string): Promise<void> {
    this.#upsertRun(await stopFolderRun(runId));
    consoleLog.push('DIR', 'proceso de carpeta detenido', 'sys');
  }

  /**
   * Quitar de la pantalla una carpeta terminada, también en el servicio.
   *
   * Quitarla sólo aquí no servía: el servicio la seguía teniendo y volvía a
   * aparecer en cuanto alguien recargaba la página. Por eso se olvida en los dos
   * sitios o en ninguno; si el servicio se niega -- porque la carpeta sigue
   * viva -- la tarjeta se queda donde está.
   */
  async forgetRun(runId: string): Promise<void> {
    await forgetFolderRun(runId);
    this.runs = this.runs.filter((run) => run.id !== runId);
    consoleLog.push('DIR', 'carpeta retirada de la pantalla', 'sys');
  }

  /** Lo mismo para todas las terminadas de una vez. */
  async forgetFinishedRuns(): Promise<number> {
    const { removed } = await clearFolderRuns();
    this.runs = this.activeRuns;
    consoleLog.push('DIR', `${removed} carpeta(s) retiradas de la pantalla`, 'sys');
    return removed;
  }

  /** Empty the screen. Generated PDFs and the inventory are untouched. */
  async clear(): Promise<number> {
    this.clearing = true;
    try {
      // Lo que se lleva pendientes se guarda antes de soltarlo: en cuanto el
      // servicio olvide el trabajo, esta copia es la única que sabe qué páginas
      // quedaron por revisar y por qué.
      const pendientes = pendingReview(this.finished);
      const { removed } = await clearScreen();
      this.dismissed = [
        ...pendientes,
        ...this.dismissed.filter((old) => !pendientes.some((job) => job.id === old.id))
      ];
      this.jobs = this.inFlight;
      // También en el servicio: quitarlas sólo de aquí las hacía reaparecer en
      // cuanto alguien recargaba la página.
      try {
        await clearFolderRuns();
      } catch {
        // Vaciar la pantalla no puede fallar por esto. Si el servicio es
        // anterior a esta capacidad, las carpetas vuelven al recargar y se ve,
        // que es mejor que dejar los documentos sin limpiar.
      }
      this.runs = this.activeRuns;
      consoleLog.push('SYS', `pantalla limpiada · ${removed} documentos archivados`, 'sys');
      return removed;
    } finally {
      this.clearing = false;
    }
  }

  async remove(id: string, purge = false): Promise<void> {
    const job = this.get(id);
    await deleteJob(id, purge);
    this.jobs = this.jobs.filter((existing) => existing.id !== id);
    consoleLog.push(
      'SYS',
      purge ? 'documento y archivos eliminados' : 'documento archivado',
      'sys',
      job?.filename ?? null
    );
  }
}

export const jobStore = new JobStore();
