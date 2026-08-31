import {
  clearScreen,
  deleteJob,
  listBatches,
  listFolderRuns,
  listJobs,
  startFolderRun,
  stopFolderRun,
  streamEvents
} from './api';
import { consoleLog } from './console.svelte';
import type { FolderRun, Job, SourceDisposition } from './types';

/**
 * The live workspace, shared by every route.
 *
 * It lives here rather than in a page component because the detail view is a
 * route of its own: state owned by the workspace page would be torn down on
 * navigation, taking the event stream with it and reconnecting on the way back.
 * One connection, opened by the layout, outlives every route change.
 */
class JobStore {
  jobs = $state<Job[]>([]);
  runs = $state<FolderRun[]>([]);
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
    return this.jobs.filter((job) => job.state === 'done' || job.state === 'failed');
  }

  /** Documents still queued or running. These keep their live card. */
  get inFlight(): Job[] {
    return this.jobs.filter((job) => job.state === 'queued' || job.state === 'running');
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

  /** Empty the screen. Generated PDFs and the inventory are untouched. */
  async clear(): Promise<number> {
    this.clearing = true;
    try {
      const { removed } = await clearScreen();
      this.jobs = this.inFlight;
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
