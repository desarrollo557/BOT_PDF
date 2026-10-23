<script lang="ts">
  import { createBatch, uploadDocument, withConcurrency } from '$lib/api';
  import { confirmar } from '$lib/confirmar.svelte';
  import BatchMonitor from '$lib/components/BatchMonitor.svelte';
  import ColaDeProcesos, { type Proceso } from '$lib/components/ColaDeProcesos.svelte';
  import EncabezadoDePagina from '$lib/components/EncabezadoDePagina.svelte';
  import FolderRunMonitor from '$lib/components/FolderRunMonitor.svelte';
  import JobCard from '$lib/components/JobCard.svelte';
  import SingleDocumentMonitor from '$lib/components/SingleDocumentMonitor.svelte';
  import UploadPanel from '$lib/components/UploadPanel.svelte';
  import { consoleLog } from '$lib/console.svelte';
  import type { AgruparChoice, CorteChoice } from '$lib/habilidades';
  import type { LecturaChoice } from '$lib/lectura';
  import type { TipoPedido } from '$lib/tipos';
  import type { OracleChoice } from '$lib/oracles';
  import { formatBytes } from '$lib/format';
  import { jobStore } from '$lib/jobs.svelte';
  import { reports, summarise } from '$lib/report.svelte';
  import type { TaskKind } from '$lib/types';

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
      jobs.some(
        (job) => job.state === 'queued' || job.state === 'running' || job.state === 'paused'
      )
    )
  );

  /**
   * Los documentos que se dibujan por su cuenta.
   *
   * Ni los de un lote ni los de una carpeta: los dos tienen ya quien informe por
   * ellos. Una carpeta que además dibujara una tarjeta por cada PDF que va
   * consumiendo enseñaría lo mismo dos veces -- una vez dentro de su árbol y
   * otra como si fuera una carga suelta de la misma tarde.
   */
  const enCarpeta = $derived(new Set(jobStore.runs.flatMap((run) => run.job_ids ?? [])));
  const looseInFlight = $derived(
    inFlight.filter((job) => !job.batch_id && !enCarpeta.has(job.id))
  );

  /**
   * Las carpetas de esta sesión, separadas por si siguen vivas.
   *
   * Una corrida terminada no se va sola de la pantalla: su árbol es donde están
   * los PDF que produjo y el botón que baja su inventario, y mandar al operador
   * al archivo a buscar la carpeta que tiene delante es hacerle dar un rodeo.
   *
   * Pero tampoco puede quedarse mezclada con la que sí está trabajando. Al cabo
   * de una mañana la pantalla enseñaba media docena de tarjetas cerradas, con
   * sus contadores y sus colas, y encontrar la viva entre ellas costaba leerlas
   * todas. Así que arriba va lo que corre y debajo, en su propio apartado, lo
   * que ya cerró -- con la opción de retirarlo cuando estorbe.
   */
  const runs = $derived(jobStore.runs);
  const liveRuns = $derived(jobStore.activeRuns);
  const closedRuns = $derived(runs.filter((run) => !liveRuns.includes(run)));

  let clearingRuns = $state(false);
  let runsError = $state<string | null>(null);

  async function forgetClosedRuns() {
    const seguro = await confirmar({
      titulo: `¿Quitar las ${closedRuns.length} carpetas terminadas?`,
      mensaje:
        'Sólo se quitan las tarjetas: lo entregado sigue en las carpetas de destino y en el archivo.',
      aceptar: 'Quitar todas'
    });
    if (!seguro) return;
    clearingRuns = true;
    runsError = null;
    try {
      await jobStore.forgetFinishedRuns();
    } catch (problem) {
      runsError = (problem as Error).message;
    } finally {
      clearingRuns = false;
    }
  }
  const busy = $derived(
    activeBatches.length > 0 ||
      looseInFlight.length > 0 ||
      jobStore.activeRuns.length > 0 ||
      uploading
  );

  /* Hay algo que poner en la columna de la derecha. Lo terminado cuenta: si sólo
     contara lo que corre, el árbol de la carpeta desaparecería justo cuando el
     operador va a usarlo. */
  const conAlgoQueVer = $derived(busy || runs.length > 0);

  const inFlightBytes = $derived(inFlight.reduce((sum, job) => sum + (job.bytes ?? 0), 0));

  /**
   * El flujo de la pantalla tiene dos niveles.
   *
   * Sin nada en curso, el asistente de carga ocupa la columna: es lo único que
   * hay que hacer. Con algo en curso, la columna pasa a ser la cola -- qué
   * corre, en qué orden, cuánto lleva -- y el asistente se abre sólo cuando se
   * pide agregar otro proceso. Así no queda a la vista, a medio rellenar, un
   * formulario que nadie está usando mientras el trabajo corre al lado.
   */
  let agregando = $state(false);

  const procesos = $derived.by<Proceso[]>(() => {
    const lista: Proceso[] = [];
    for (const run of liveRuns) {
      const tomados = run.processed + run.failed;
      lista.push({
        ancla: `proceso-carpeta-${run.id}`,
        tipo: 'carpeta',
        nombre: run.source.split(/[\\/]/).filter(Boolean).at(-1) ?? run.source,
        estado:
          run.state === 'watching'
            ? 'vigilando'
            : run.state === 'recovering'
              ? 'en pausa'
              : 'procesando',
        avance: run.discovered ? Math.min(100, (100 * tomados) / run.discovered) : null,
        detalle:
          `${tomados} de ${run.discovered} documentos` +
          (run.en_curso && run.en_curso.length > 1 ? ` · ${run.en_curso.length} a la vez` : '') +
          (run.failed ? ` · ${run.failed} con fallo` : '')
      });
    }
    for (const [batchId, jobs] of activeBatches) {
      const cerrados = jobs.filter(
        (job) => job.state === 'done' || job.state === 'failed' || job.state === 'cancelled'
      ).length;
      const corriendo = jobs.some((job) => job.state === 'running');
      const pausado = jobs.some((job) => job.state === 'paused');
      lista.push({
        ancla: `proceso-lote-${batchId}`,
        tipo: 'lote',
        nombre: jobStore.batchNames[batchId] ?? `Lote de ${jobs.length} documentos`,
        estado: corriendo ? 'procesando' : pausado ? 'en pausa' : 'en cola',
        avance: jobs.length ? (100 * cerrados) / jobs.length : null,
        detalle: `${cerrados} de ${jobs.length} documentos`
      });
    }
    for (const job of looseInFlight) {
      lista.push({
        ancla: `proceso-doc-${job.id}`,
        tipo: 'documento',
        nombre: job.filename,
        estado:
          job.state === 'running' ? 'procesando' : job.state === 'paused' ? 'en pausa' : 'en cola',
        avance: job.progress.percent || null,
        detalle: job.progress.page_count
          ? `${job.progress.pages_done} de ${job.progress.page_count} páginas`
          : 'esperando turno'
      });
    }
    return lista;
  });

  // Lo agregado aparece en la cola y el asistente se pliega solo: el operador
  // ve enseguida que su proceso entró, en su sitio de la fila.
  let procesosAntes = 0;
  $effect(() => {
    const ahora = procesos.length;
    if (ahora > procesosAntes) agregando = false;
    procesosAntes = ahora;
  });

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
      if (
        jobs.some(
          (job) => job.state === 'queued' || job.state === 'running' || job.state === 'paused'
        )
      ) {
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
      // A document taken from a folder is reported with its run, not alone.
      // Por su origen y no sólo por la lista de la corrida: el PDF puede
      // terminar antes de que esa lista llegue a la pantalla, y entonces se
      // contaba dos veces -- suelto y dentro de su carpeta --, que es como
      // una carpeta de 10 PDF salía en el informe con 11 documentos.
      if (
        job.origen?.tipo === 'carpeta' ||
        jobStore.runs.some((run) => run.job_ids?.includes(job.id))
      ) {
        continue;
      }
      const id = `doc:${job.id}`;
      if (job.state === 'queued' || job.state === 'running' || job.state === 'paused') {
        reports.watch(id);
        continue;
      }
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
    // Por su origen o por la lista de la corrida, que trae sólo los últimos.
    const ids = new Set(run.job_ids ?? []);
    const jobs = jobStore.jobs.filter((job) => ids.has(job.id) || job.origen?.id === run.id);
    // Con el nombre de la carpeta raíz, que es como se la reconoce; la ruta
    // entera va en la entrega.
    const nombre = run.source.split(/[\\/]/).filter(Boolean).at(-1) ?? run.source;
    const completion = summarise(id, 'carpeta', nombre, jobs);

    completion.destination = run.destination;
    completion.delivered = run.delivered;
    completion.entregas = [
      {
        nombre,
        origen: run.source,
        destino: run.destination,
        archivos: run.delivered,
        inventarioDe: run.inventario ? run.id : null,
        inventario: run.inventario ?? null
      }
    ];
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

  /** Cómo se nombra cada acción en la consola y en el título del lote. */
  const ACCIONES: Record<TaskKind, string> = {
    split: 'dividir',
    inventory: 'inventariar',
    both: 'dividir e inventariar',
    segment: 'separar por documento',
    inventory_file: 'inventariar el archivo'
  };

  async function handle(
    files: File[],
    asBatch: boolean,
    task: TaskKind = 'split',
    oracle: OracleChoice = 'auto',
    lectura: LecturaChoice = 'local',
    tipo: TipoPedido = 'auto',
    corte: CorteChoice = 'folio',
    agrupar: AgruparChoice = 'documento',
    territorial = '',
    paralelo = 0,
    tipoDocumento?: string
  ) {
    errors = [];
    uploaded = 0;
    uploadTotal = files.length;
    agregando = false;

    let batchId: string | undefined;
    if (asBatch) {
      const accion = ACCIONES[task];
      const name = `Lote de ${files.length} documento${files.length === 1 ? '' : 's'} ${accion}`;
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
      consoleLog.push(
        'NET',
        `${files.length} archivo(s) · carga individual · ${ACCIONES[task]}`,
        'net'
      );
    }

    await withConcurrency(files, UPLOAD_CONCURRENCY, async (file) => {
      try {
        await uploadDocument(file, batchId, task, oracle, lectura, tipo, corte, agrupar, territorial, paralelo, tipoDocumento);
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
<div class="workspace-frame">
<div class="workspace" class:busy={conAlgoQueVer}>
  <!-- El encabezado de la pantalla, como en Archivo: ocupa la fila entera de la
       rejilla, así queda alineado con el asistente cuando está solo y con las
       dos columnas cuando hay trabajo corriendo. -->
  <div class="cabecera">
    <EncabezadoDePagina
      titulo="Procesar"
      descripcion="Elija qué va a procesar, cómo se lee y qué se entrega."
    />
  </div>

  <section class="intake">
    {#if busy && !agregando}
      <ColaDeProcesos {procesos} onagregar={() => (agregando = true)} subiendo={uploading} />
    {:else}
      <div class="intake-head">
        {#if busy}
          <!-- Un nivel por debajo de la cola: se dice, y se puede volver. -->
          <nav class="sub-nivel" aria-label="Dónde está">
            <button type="button" onclick={() => (agregando = false)}>
              ← Procesos en curso ({procesos.length})
            </button>
            <span>› Agregar a la cola</span>
          </nav>
          <h2>Agregar otro proceso a la cola</h2>
        {:else}
          <h2>Cargar documentos</h2>
        {/if}
      </div>

      <UploadPanel onfiles={handle} disabled={uploading} />
    {/if}

    {#if uploading}
      <div class="progress">
        <div class="track">
          <div class="fill" style:width={`${(uploaded / uploadTotal) * 100}%`}></div>
        </div>
        <p class="tabular">Subiendo {uploaded} de {uploadTotal} archivos…</p>
      </div>
    {/if}

    {#each errors as message}
      <p class="inline-error">{message}</p>
    {/each}

    {#if busy && inFlightBytes}
      <p class="weighing tabular">
        {inFlight.length} documento{inFlight.length === 1 ? '' : 's'} en curso ·
        {formatBytes(inFlightBytes)} en proceso
      </p>
    {/if}
  </section>

  {#if conAlgoQueVer}
    <section class="live">
      {#each liveRuns as run (run.id)}
        <div class="ancla" id={`proceso-carpeta-${run.id}`}><FolderRunMonitor {run} /></div>
      {/each}

      {#each activeBatches as [batchId, batchJobs] (batchId)}
        <div class="ancla" id={`proceso-lote-${batchId}`}>
          <BatchMonitor
            name={jobStore.batchNames[batchId] ?? `Lote de ${batchJobs.length} documentos`}
            jobs={batchJobs}
            {batchId}
          />
        </div>
      {/each}

      {#if looseInFlight.length === 1}
        <!-- One document alone earns the full panel: with nothing to compare it
             against, the detail is what there is to look at. -->
        <div class="ancla" id={`proceso-doc-${looseInFlight[0].id}`}>
          <SingleDocumentMonitor job={looseInFlight[0]} />
        </div>
      {:else if looseInFlight.length}
        {#each looseInFlight as job (job.id)}
          <div class="ancla" id={`proceso-doc-${job.id}`}><JobCard {job} /></div>
        {/each}
      {/if}

      {#if closedRuns.length}
        <section class="closed">
          <header>
            <h3>Carpetas terminadas ({closedRuns.length})</h3>
            <button class="btn btn-sm btn-ghost" onclick={forgetClosedRuns} disabled={clearingRuns}>
              {clearingRuns ? 'Quitando…' : 'Quitar todas'}
            </button>
          </header>
          {#if runsError}
            <p class="inline-error">{runsError}</p>
          {/if}
          {#each closedRuns as run (run.id)}
            <FolderRunMonitor {run} />
          {/each}
        </section>
      {/if}
    </section>
  {:else}
    <aside class="hint">
      <p class="closing">
        Lo que termine se guarda en el <a href="/archivo">archivo</a>, con su fecha, y lo que
        necesite un ojo humano queda listado en <a href="/revision">revisión</a>.
      </p>
    </aside>
  {/if}
</div>
</div>

<style>
  /* Lo que ya cerró, apartado de lo que corre. Mismo contenido, menos peso
     visual: sigue estando entero -- su árbol, su inventario -- pero deja de
     competir por la mirada con la carpeta que sí está trabajando. */
  .closed {
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
    margin-top: 0.4rem;
    border-top: 1px solid var(--rule);
    padding-top: 0.9rem;
  }
  .closed header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.6rem;
  }
  .closed h3 {
    margin: 0;
    font-size: var(--text-sm);
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--ink-2);
  }
  /* Los fallos van en `.inline-error`; aquí sólo se le quita el margen, que
     el hueco de la columna ya separa. */
  .closed .inline-error,
  .intake > .inline-error {
    margin: 0;
  }

  /* Idle: the intake takes the free width beside the console, so the options
     of each step sit side by side instead of in one long column that has to be
     scrolled. It was a centred 34rem column, and on a wide screen that left
     more empty space than form. Busy: the work takes the right-hand side and
     the intake stays put on the left.

     Measured on the space actually left for the page, not on the window: the
     console takes up to half of it, and a breakpoint on the viewport width
     put two columns in a room that only fits one. */
  .workspace-frame {
    container: workspace / inline-size;
  }
  .workspace {
    display: grid;
    justify-content: center;
    gap: 1.5rem;
    grid-template-columns: minmax(0, 72rem);
  }
  .workspace.busy {
    justify-content: stretch;
  }
  .cabecera {
    grid-column: 1 / -1;
  }
  /* El hueco de la rejilla ya separa el encabezado de lo que sigue. */
  .cabecera :global(.encabezado) {
    margin-bottom: 0;
  }
  @container workspace (min-width: 62rem) {
    .workspace.busy {
      align-items: start;
      grid-template-columns: minmax(0, 26rem) minmax(0, 1fr);
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

  /* Lo que salta a un monitor desde la cola queda debajo de la barra fija. */
  .ancla {
    scroll-margin-top: 5.5rem;
  }

  .sub-nivel {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem;
    margin-bottom: 0.4rem;
    font-size: var(--text-sm);
    color: var(--muted);
  }
  .sub-nivel button {
    border: 0;
    background: none;
    padding: 0;
    font: inherit;
    color: var(--accent);
    cursor: pointer;
  }
  .sub-nivel button:hover {
    text-decoration: underline;
  }

  .intake-head h2 {
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 650;
    letter-spacing: -0.015em;
  }

  .progress .track {
    height: 6px;
    overflow: hidden;
    border-radius: var(--radius-pill);
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
    font-size: var(--text-sm);
    color: var(--muted);
  }

  .weighing {
    margin: 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .live {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 1.1rem;
  }

  .closing {
    margin: 0;
    font-size: var(--text-sm);
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
