<script lang="ts">
  import { createBatch, uploadDocument, withConcurrency } from '$lib/api';
  import BatchMonitor from '$lib/components/BatchMonitor.svelte';
  import FolderRunMonitor from '$lib/components/FolderRunMonitor.svelte';
  import JobCard from '$lib/components/JobCard.svelte';
  import SingleDocumentMonitor from '$lib/components/SingleDocumentMonitor.svelte';
  import UploadPanel from '$lib/components/UploadPanel.svelte';
  import { consoleLog } from '$lib/console.svelte';
  import { formatBytes } from '$lib/format';
  import { jobStore } from '$lib/jobs.svelte';
  import { reports, summarise } from '$lib/report.svelte';

  /**
   * Uploads in flight at once. Fifty parallel transfers of a few hundred
   * megabytes each only starve one another; a small window keeps every one of
   * them moving and the queue filling steadily.
   */
  const UPLOAD_CONCURRENCY = 3;

  let uploaded = $state(0);
  let uploadTotal = $state(0);
  let errors = $state<string[]>([]);

  const uploading = $derived(uploadTotal > 0 && uploaded < uploadTotal);
  const inFlight = $derived(jobStore.inFlight);

  /**
   * Batches with work still open. A settled batch leaves this screen entirely:
   * the workspace is for what is happening, and finished documents live on the
   * processed screen.
   */
  const allBatches = $derived.by(() => {
    const buckets = new Map<string, typeof inFlight>();
    for (const job of jobStore.jobs) {
      if (!job.batch_id) continue;
      if (!buckets.has(job.batch_id)) buckets.set(job.batch_id, []);
      buckets.get(job.batch_id)!.push(job);
    }
    return [...buckets.entries()];
  });

  const activeBatches = $derived(
    allBatches.filter(([, jobs]) =>
      jobs.some((job) => job.state === 'queued' || job.state === 'running')
    )
  );

  const looseInFlight = $derived(inFlight.filter((job) => !job.batch_id));
  const runs = $derived(jobStore.activeRuns);
  const busy = $derived(
    activeBatches.length > 0 || looseInFlight.length > 0 || runs.length > 0 || uploading
  );

  const inFlightBytes = $derived(inFlight.reduce((sum, job) => sum + (job.bytes ?? 0), 0));

  /**
   * Raise a report when a unit of work settles -- and only then.
   *
   * The live view disappearing is not an answer; the operator watched it run
   * and is owed what it did. But the service keeps finished work in memory, so
   * on every reload it all arrives again as "done". Only a unit this tab saw in
   * flight gets a modal; everything else is filed silently into the history.
   */
  $effect(() => {
    for (const [batchId, jobs] of allBatches) {
      const id = `lote:${batchId}`;
      if (jobs.some((job) => job.state === 'queued' || job.state === 'running')) {
        reports.watch(id);
        continue;
      }
      reports.register(
        summarise(
          id,
          'lote',
          jobStore.batchNames[batchId] ?? `Lote de ${jobs.length} documentos`,
          jobs
        )
      );
    }

    for (const job of jobStore.jobs) {
      if (job.batch_id) continue;
      const id = `doc:${job.id}`;
      if (job.state === 'queued' || job.state === 'running') {
        reports.watch(id);
        continue;
      }
      // A document taken from a folder is reported with its run, not alone.
      if (jobStore.runs.some((run) => run.job_ids?.includes(job.id))) continue;
      reports.register(summarise(id, 'documento', job.filename, [job]));
    }

    for (const run of jobStore.runs) {
      const id = `carpeta:${run.id}`;
      if (run.state !== 'done' && run.state !== 'stopped') {
        reports.watch(id);
        continue;
      }
      reports.register(fromRun(id, run));
    }

    // Lo último: mientras quede algo moviéndose no se muestra nada, y cuando
    // todo para sale un solo informe con lo que haya terminado.
    reports.settle(busy);
  });

  /**
   * Build a folder run's report from the run's own totals.
   *
   * Its documents leave the registry -- cleared, or forgotten on a restart --
   * long before anyone reopens the report. Summing the jobs then yields zero
   * pages and zero bytes, which is not a gap in the report, it is the report
   * stating something untrue. The run carries its own totals for exactly this.
   */
  function fromRun(id: string, run: (typeof jobStore.runs)[number]) {
    const jobs = jobStore.jobs.filter((job) => run.job_ids?.includes(job.id));
    const completion = summarise(id, 'carpeta', run.source, jobs);

    completion.destination = run.destination;
    completion.delivered = run.delivered;
    completion.operator = completion.operator ?? run.operator;
    // The run is the authority on its own totals; the jobs are only richer
    // while they are still around.
    completion.documents = run.processed + run.failed;
    completion.failedDocuments = run.failed;
    completion.resolutions = Math.max(completion.resolutions, run.resolutions);
    completion.pages = Math.max(completion.pages, run.pages_total ?? 0);
    completion.bytes = Math.max(completion.bytes, run.bytes_total ?? 0);

    if (!completion.elapsedSeconds) {
      const from = Date.parse(run.started_at);
      const to = run.finished_at ? Date.parse(run.finished_at) : NaN;
      if (!Number.isNaN(from) && !Number.isNaN(to)) {
        completion.elapsedSeconds = Math.max(0, (to - from) / 1000);
      }
    }
    return completion;
  }

  async function handle(files: File[], asBatch: boolean) {
    errors = [];
    uploaded = 0;
    uploadTotal = files.length;

    let batchId: string | undefined;
    if (asBatch) {
      const name = `Lote de ${files.length} documento${files.length === 1 ? '' : 's'}`;
      consoleLog.push('NET', `lote de ${files.length} archivos · abriendo`, 'net');
      try {
        batchId = (await createBatch(name)).id;
        jobStore.nameBatch(batchId, name);
      } catch (error) {
        // A batch is a label, not a prerequisite. If it fails, the documents
        // still get processed; they just show up ungrouped.
        errors = [...errors, `No se pudo abrir el lote: ${(error as Error).message}`];
        consoleLog.push('WARN', `no se pudo abrir el lote: ${(error as Error).message}`, 'warn');
      }
    } else {
      consoleLog.push('NET', `${files.length} archivo(s) · carga individual`, 'net');
    }

    await withConcurrency(files, UPLOAD_CONCURRENCY, async (file) => {
      try {
        await uploadDocument(file, batchId);
        consoleLog.push('UP', `${formatBytes(file.size)} subidos`, 'net', file.name);
      } catch (error) {
        errors = [...errors, `${file.name}: ${(error as Error).message}`];
        consoleLog.push('FAIL', (error as Error).message, 'fail', file.name);
      } finally {
        uploaded += 1;
      }
    });
    consoleLog.push('NET', `subida completa · ${uploaded}/${uploadTotal} archivos`, 'net');
  }
</script>

<!-- One job for this screen: take documents in, and show the work while it is
     happening. Nothing that has finished belongs here -- it is on Procesados,
     and the count on that tab is what says so. -->
<div class="workspace" class:busy>
  <section class="intake">
    <div class="intake-head">
      <h2>Cargar documentos</h2>
      <p>
        Cada página se dirige a la resolución que le corresponde. Una página sin número queda con
        la resolución anterior, hasta que aparezca una nueva.
      </p>
    </div>

    <UploadPanel onfiles={handle} disabled={uploading} />

    {#if uploading}
      <div class="progress">
        <div class="track">
          <div class="fill" style:width={`${(uploaded / uploadTotal) * 100}%`}></div>
        </div>
        <p class="tabular">Subiendo {uploaded} de {uploadTotal} archivos…</p>
      </div>
    {/if}

    {#each errors as message}
      <p class="error">{message}</p>
    {/each}

    {#if busy && inFlightBytes}
      <p class="weighing tabular">
        {inFlight.length} documento{inFlight.length === 1 ? '' : 's'} en curso ·
        {formatBytes(inFlightBytes)} en proceso
      </p>
    {/if}
  </section>

  {#if busy}
    <section class="live">
      {#each runs as run (run.id)}
        <FolderRunMonitor {run} />
      {/each}

      {#each activeBatches as [batchId, batchJobs] (batchId)}
        <BatchMonitor
          name={jobStore.batchNames[batchId] ?? `Lote de ${batchJobs.length} documentos`}
          jobs={batchJobs}
        />
      {/each}

      {#if looseInFlight.length === 1}
        <!-- One document alone earns the full panel: with nothing to compare it
             against, the detail is what there is to look at. -->
        <SingleDocumentMonitor job={looseInFlight[0]} />
      {:else if looseInFlight.length}
        {#each looseInFlight as job (job.id)}
          <JobCard {job} />
        {/each}
      {/if}
    </section>
  {:else}
    <aside class="hint">
      <ol>
        <li>
          <b>Carga individual</b>
          <span>hasta cinco documentos, con la estadística completa de cada uno</span>
        </li>
        <li>
          <b>Carga por lotes</b>
          <span>sin límite de cantidad, con el peso neto y el avance del lote entero</span>
        </li>
        <li>
          <b>Carpeta local</b>
          <span>toma un PDF por vez de una carpeta y entrega las resoluciones en otra</span>
        </li>
      </ol>
      <p class="closing">
        Lo que termine se guarda en el <a href="/archivo">archivo</a>, con su fecha, y lo que
        necesite un ojo humano queda listado en <a href="/revision">revisión</a>.
      </p>
    </aside>
  {/if}
</div>

<style>
  /* Idle: one column, centred, nothing but the intake. Busy: the work takes the
     right-hand side and the intake stays put on the left. */
  .workspace {
    display: grid;
    justify-content: center;
    gap: 1.75rem;
    grid-template-columns: minmax(0, 34rem);
    padding-top: 2rem;
  }
  .workspace.busy {
    justify-content: stretch;
    padding-top: 0;
  }
  @media (min-width: 1280px) {
    .workspace.busy {
      align-items: start;
      grid-template-columns: minmax(0, 25rem) minmax(0, 1fr);
    }
  }

  .intake {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  .busy .intake {
    position: sticky;
    top: 5.75rem;
  }

  .intake-head h2 {
    margin: 0;
    font-size: 1.15rem;
    font-weight: 650;
    letter-spacing: -0.015em;
  }
  .intake-head p {
    margin: 0.35rem 0 0;
    max-width: 52ch;
    font-size: 0.84rem;
    line-height: 1.5;
    color: var(--muted);
  }
  .busy .intake-head p {
    display: none;
  }

  .progress .track {
    height: 6px;
    overflow: hidden;
    border-radius: 999px;
    background: var(--grid);
  }
  .progress .fill {
    height: 100%;
    border-radius: 0 4px 4px 0;
    background: var(--accent);
    transition: width 0.2s;
  }
  .progress p {
    margin: 0.45rem 0 0;
    font-size: 0.8rem;
    color: var(--muted);
  }

  .error {
    margin: 0;
    border-left: 2px solid var(--critical);
    padding-left: 0.65rem;
    font-size: 0.82rem;
    color: var(--critical);
  }

  .weighing {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--muted);
  }

  .live {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 1.1rem;
  }

  .hint ol {
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .hint li {
    display: flex;
    flex-direction: column;
    gap: 1px;
    border-left: 2px solid var(--rule);
    padding-left: 0.8rem;
  }
  .hint b {
    font-size: 0.82rem;
    font-weight: 600;
  }
  .hint span {
    font-size: 0.78rem;
    line-height: 1.45;
    color: var(--muted);
  }

  .closing {
    margin: 1.1rem 0 0;
    border-top: 1px solid var(--rule);
    padding-top: 0.9rem;
    font-size: 0.8rem;
    color: var(--muted);
  }
  .closing a {
    color: var(--accent);
    text-decoration: none;
  }
  .closing a:hover {
    text-decoration: underline;
  }
</style>
