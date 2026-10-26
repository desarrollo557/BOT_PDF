<script lang="ts">
  import RunControls from '$lib/components/RunControls.svelte';
  import Descargas, { type GrupoDeDescargas } from '$lib/components/Descargas.svelte';
  import { descargarPlanilla, origenInventarioUrl, origenProcesosUrl } from '$lib/api';
  import { onMount } from 'svelte';
  import PageRibbon from '$lib/components/PageRibbon.svelte';
  import RunStats from '$lib/components/RunStats.svelte';
  import PanelDeRendimiento from '$lib/components/PanelDeRendimiento.svelte';
  import { marcadasEnCinta, sumarConsumos } from '$lib/rendimiento';
  import { formatBytes, formatDuration, unitFor } from '$lib/format';
  import { STAGE_LABELS } from '$lib/rungs';
  import type { Job } from '$lib/types';

  interface Props {
    name: string;
    jobs: Job[];
    /** Para poder pausar o cancelar el lote entero de una sola orden. */
    batchId?: string;
  }

  let { name, jobs, batchId }: Props = $props();

  const running = $derived(jobs.filter((job) => job.state === 'running'));
  const queued = $derived(jobs.filter((job) => job.state === 'queued'));
  const paused = $derived(jobs.filter((job) => job.state === 'paused'));
  const done = $derived(jobs.filter((job) => job.state === 'done'));
  const failed = $derived(jobs.filter((job) => job.state === 'failed'));
  const cancelled = $derived(jobs.filter((job) => job.state === 'cancelled'));

  /**
   * En qué está el lote, para decidir si se ofrece pausar o reanudar.
   *
   * Se considera en pausa cuando ya no queda ninguno corriendo: con cincuenta
   * documentos, la orden llega a todos pero cada uno la atiende al terminar su
   * página, y durante esos segundos el lote está parándose, no parado.
   */
  const batchState = $derived.by(() => {
    if (running.length) return 'running' as const;
    if (paused.length) return 'paused' as const;
    if (queued.length) return 'queued' as const;
    return 'done' as const;
  });

  const pagesTotal = $derived(jobs.reduce((sum, job) => sum + job.progress.page_count, 0));
  const pagesDone = $derived(jobs.reduce((sum, job) => sum + job.progress.pages_done, 0));
  const percent = $derived(jobs.length ? (100 * (done.length + failed.length)) / jobs.length : 0);
  const rate = $derived(running.reduce((sum, job) => sum + job.progress.pages_per_second, 0));
  const resolutions = $derived(
    jobs.reduce((sum, job) => sum + (job.report?.groups?.length ?? 0), 0)
  );
  const settled = $derived(
    jobs.length > 0 && done.length + failed.length + cancelled.length === jobs.length
  );

  /**
   * Net weight of the batch: every source PDF added up, and how much of it has
   * been read. Bytes read are apportioned by each document's own progress, so a
   * half-read 200 MB file counts as 100 MB rather than as nothing or as all.
   */
  const bytesTotal = $derived(jobs.reduce((sum, job) => sum + (job.bytes ?? 0), 0));
  const bytesDone = $derived(
    jobs.reduce((sum, job) => sum + ((job.bytes ?? 0) * job.progress.percent) / 100, 0)
  );
  const heaviest = $derived(
    jobs.reduce<Job | null>(
      (top, job) => ((job.bytes ?? 0) > (top?.bytes ?? 0) ? job : top),
      null
    )
  );

  /**
   * Wall clock for the whole batch: first document to start, last to finish.
   *
   * Not the sum of the per-document times -- eleven workers run at once, so
   * that sum is worker-seconds and would report a two-minute batch as twenty.
   * What the operator waited is the span, and once the batch settles that span
   * is how long it took, which is the number they came back to read.
   */
  let now = $state(Date.now());
  onMount(() => {
    const tick = setInterval(() => (now = Date.now()), 500);
    return () => clearInterval(tick);
  });

  function stamp(value: string | null): number | null {
    if (!value) return null;
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? null : parsed;
  }

  const elapsedSeconds = $derived.by(() => {
    const starts = jobs.map((job) => stamp(job.started_at)).filter((v): v is number => v !== null);
    if (!starts.length) return 0;
    const from = Math.min(...starts);
    if (!settled) return Math.max(0, (now - from) / 1000);

    const ends = jobs.map((job) => stamp(job.finished_at)).filter((v): v is number => v !== null);
    if (!ends.length) return Math.max(0, (now - from) / 1000);
    return Math.max(0, (Math.max(...ends) - from) / 1000);
  });

  const elapsed = $derived(elapsedSeconds >= 1 ? formatDuration(elapsedSeconds) : '—');

  /** Bytes per second across the batch, which is what sizes a nightly window. */
  const byteRate = $derived(elapsedSeconds >= 1 ? bytesDone / elapsedSeconds : 0);

  /**
   * Live throughput while documents are open, the batch average once they are
   * all closed. A speed that reads "—" the moment the work finishes throws away
   * the one measurement the run was for.
   */
  const speed = $derived.by(() => {
    if (rate) return `${rate.toFixed(1)} p/s`;
    if (elapsedSeconds >= 1 && pagesDone) return `${(pagesDone / elapsedSeconds).toFixed(1)} p/s`;
    return '—';
  });

  /** Time left from the throughput actually being achieved, not from an average. */
  const remainingSeconds = $derived.by(() => {
    if (!rate || pagesDone >= pagesTotal) return null;
    return (pagesTotal - pagesDone) / rate;
  });

  /**
   * La velocidad viva mientras hay documentos abiertos, la media del lote una
   * vez cerrados todos. Una velocidad que pone "—" justo al terminar tira la
   * única medición para la que se hizo la corrida.
   */
  const rateShown = $derived(
    rate || (elapsedSeconds >= 1 && pagesDone ? pagesDone / elapsedSeconds : 0)
  );

  /**
   * Los dos inventarios generales del lote, en cuanto termina el primer PDF:
   * el de la habilidad -- el Índice Electrónico de las cajas de
   * correspondencia, una hoja por PDF -- y el general del bot, una fila por
   * PDF procesado. Se rehacen con cada PDF que termina.
   */
  const descargas = $derived<GrupoDeDescargas[]>(
    batchId && done.length + failed.length
      ? [
          {
            titulo: 'Inventarios generales del lote',
            items: [
              ...(done.some((job) => job.report?.indice_electronico)
                ? [
                    {
                      id: 'indice',
                      titulo: 'Índice electrónico',
                      detalle: 'Plantilla del cliente, una hoja por PDF procesado',
                      formato: 'Excel' as const,
                      principal: true,
                      bajar: () =>
                        descargarPlanilla(origenInventarioUrl(batchId), '00.INDICE ELECTRONICO.xlsx')
                    }
                  ]
                : []),
              {
                id: 'procesos',
                titulo: 'Inventario de procesos',
                detalle: 'Lo que hizo el bot con cada PDF: habilidad, lectura, resultado y revisión',
                formato: 'Excel' as const,
                bajar: () =>
                  descargarPlanilla(
                    origenProcesosUrl(batchId),
                    '00.INVENTARIO GENERAL DE PROCESOS.xlsx'
                  )
              }
            ]
          }
        ]
      : []
  );

  /** El punto de cada documento de la cola: en curso, listo o con error; el
   * resto (en cola, en pausa, cancelado) queda gris. */
  const TONO_DE_CHIP: Partial<Record<Job['state'], string>> = {
    // Quieto: con veinte chips en curso, que latan todos sería ruido.
    running: 'accent',
    done: 'good',
    failed: 'bad'
  };

  /** Lo que salió del lote, llamado por su nombre. */
  const unitLabel = $derived(unitFor(done[0]?.report?.stats, resolutions));
</script>

<section class="monitor panel" class:settled>
  <header class="head">
    <span class="status-dot {settled ? 'good' : 'live'}" aria-hidden="true"></span>
    <h3>{name}</h3>
    <span class="counter tabular">{done.length + failed.length} / {jobs.length} documentos</span>
    {#if batchId}
      <!-- Una sola orden para el lote entero: pausar cincuenta documentos de uno
           en uno no es una función, es un castigo. -->
      <RunControls {batchId} runState={batchState} documents={jobs.length} />
    {/if}
  </header>

  <div
    class="progress"
    role="progressbar"
    aria-valuenow={Math.round(percent)}
    aria-valuemin="0"
    aria-valuemax="100"
  >
    <div class="progress-fill" class:good={settled} style:width={`${percent}%`}></div>
  </div>

  <RunStats
    {pagesDone}
    {pagesTotal}
    units={resolutions}
    {unitLabel}
    {bytesTotal}
    {bytesDone}
    rate={rateShown}
    {elapsedSeconds}
    {remainingSeconds}
    queued={queued.length}
    failed={failed.length}
    {settled}
  />

  <div class="now">
    <PanelDeRendimiento
      paginasHechas={pagesDone}
      paginasTotal={pagesTotal}
      velocidad={rate}
      segundos={elapsedSeconds}
      etapas={running.map((job) => job.progress.stage)}
      procedencias={jobs.map((job) => job.progress.by_provenance)}
      revision={jobs.reduce((sum, job) => sum + marcadasEnCinta(job.progress.ribbon), 0)}
      fallidas={jobs.reduce((sum, job) => sum + job.progress.failed_pages, 0)}
      documentos={{
        hechos: done.length,
        fallidos: failed.length + cancelled.length,
        enCola: queued.length + paused.length + running.length,
        total: jobs.length
      }}
      consumo={sumarConsumos(jobs.map((job) => job.progress.consumo ?? job.report?.consumo))}
      vivo={!settled}
    />
    {#if heaviest && jobs.length > 1}
      <p class="footnote">
        El más pesado del lote es <b>{heaviest.filename}</b> con {formatBytes(heaviest.bytes)},
        el {bytesTotal ? ((100 * heaviest.bytes) / bytesTotal).toFixed(0) : 0} % del peso total.
      </p>
    {/if}
  </div>

  {#if descargas.length}
    <div class="descargas"><Descargas grupos={descargas} /></div>
  {/if}

  {#if running.length}
    <!-- The answer to "which file is it on right now". One block per worker,
         because eleven processes means eleven documents are open at once and a
         single "current file" would simply be untrue. -->
    <div class="now">
      <span class="caps section-label">Leyendo ahora ({running.length})</span>
      {#each running as job (job.id)}
        <article class="current">
          <div class="line">
            <span class="status-dot status-dot-sm live" aria-hidden="true"></span>
            <span class="file" title={job.filename}>{job.filename}</span>
            <span class="stage">{STAGE_LABELS[job.progress.stage] ?? job.progress.stage}</span>
            <span class="pages tabular">
              {job.progress.pages_done}/{job.progress.page_count || '?'}
            </span>
          </div>
          <div class="progress progress-sm">
            <div class="progress-fill" style:width={`${job.progress.percent}%`}></div>
          </div>
          {#if job.progress.page_count}
            <PageRibbon ribbon={job.progress.ribbon} pageCount={job.progress.page_count} />
          {/if}
        </article>
      {/each}
    </div>
  {/if}

  {#if jobs.length}
    <div class="queue">
      <span class="caps section-label">
        Cola del lote — {done.length} listos, {queued.length} esperando{failed.length
          ? `, ${failed.length} con error`
          : ''}
      </span>
      <ul>
        {#each jobs as job (job.id)}
          <li data-state={job.state} title={job.filename}>
            <span class="status-dot status-dot-sm {TONO_DE_CHIP[job.state] ?? ''}" aria-hidden="true"></span>
            <span class="chip-name">{job.filename}</span>
          </li>
        {/each}
      </ul>
    </div>
  {/if}
</section>

<style>
  /* La tarjeta es el `.panel` común. Mientras el lote corre, el filete lleva un
     tinte del acento: algo en curso. */
  .monitor {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .monitor:not(.settled) {
    border-color: color-mix(in srgb, var(--accent) 30%, var(--hairline));
  }

  .head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .head h3 {
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 650;
    letter-spacing: -0.01em;
  }
  .counter {
    margin-left: auto;
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .footnote {
    margin: var(--space-2) 0 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .footnote b {
    color: var(--ink-2);
  }

  .section-label {
    display: block;
    margin-bottom: var(--space-2);
  }

  .now {
    border-top: 1px solid var(--rule);
    padding-top: var(--space-3);
  }

  .current {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    border-radius: var(--radius-md);
    background: var(--plane);
    padding: var(--space-2) var(--space-3);
  }
  .current + .current {
    margin-top: var(--space-2);
  }

  .line {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .file {
    overflow: hidden;
    font-size: var(--text-sm);
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .stage {
    flex-shrink: 0;
    font-size: var(--text-xs);
    color: var(--ink-2);
  }
  .pages {
    margin-left: auto;
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .queue {
    border-top: 1px solid var(--rule);
    padding-top: var(--space-3);
  }
  .queue ul {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .queue li {
    display: flex;
    max-width: 15rem;
    align-items: center;
    gap: var(--space-2);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-sm);
    background: var(--surface-1);
    padding: 2px var(--space-2);
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .chip-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  [data-state='running'] {
    border-color: color-mix(in srgb, var(--accent) 45%, var(--hairline));
    color: var(--ink);
  }
  [data-state='done'] {
    color: var(--ink-2);
  }
  [data-state='failed'] {
    border-color: color-mix(in srgb, var(--critical) 45%, var(--hairline));
    color: var(--critical);
  }

  .descargas {
    margin-top: var(--space-3);
    max-width: 34rem;
  }
</style>
