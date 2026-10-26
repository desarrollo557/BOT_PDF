<script lang="ts">
  import RunControls from '$lib/components/RunControls.svelte';
  import { onMount } from 'svelte';
  import PageRibbon from '$lib/components/PageRibbon.svelte';
  import RunStats from '$lib/components/RunStats.svelte';
  import PanelDeRendimiento from '$lib/components/PanelDeRendimiento.svelte';
  import { marcadasEnCinta } from '$lib/rendimiento';
  import { SILENCE_THRESHOLD_SECONDS, stageActivity } from '$lib/rungs';
  import { unitFor } from '$lib/format';
  import type { Job } from '$lib/types';

  interface Props {
    job: Job;
  }

  let { job }: Props = $props();

  let now = $state(Date.now());
  onMount(() => {
    const tick = setInterval(() => (now = Date.now()), 250);
    return () => clearInterval(tick);
  });

  const progress = $derived(job.progress);
  const running = $derived(job.state === 'running' || job.state === 'queued');

  /** Wall clock, from the moment the worker opened it. */
  const elapsedSeconds = $derived.by(() => {
    const started = job.started_at ? Date.parse(job.started_at) : NaN;
    if (Number.isNaN(started)) return 0;
    const ended = job.finished_at ? Date.parse(job.finished_at) : now;
    return Math.max(0, ((Number.isNaN(ended) ? now : ended) - started) / 1000);
  });

  const percent = $derived(progress.percent);
  const stageDone = $derived(progress.stage_done ?? progress.pages_done);
  const stageTotal = $derived(progress.stage_total ?? progress.page_count);
  const visualPercent = $derived(
    progress.percent || (stageTotal ? (100 * stageDone) / stageTotal : 0)
  );

  /** Bytes of the source read so far, apportioned by pages. */
  const bytesDone = $derived(job.bytes ? Math.round((job.bytes * percent) / 100) : 0);

  const remainingSeconds = $derived.by(() => {
    const rate = progress.pages_per_second;
    if (!rate || !progress.page_count || progress.pages_done >= progress.page_count) return null;
    return (progress.page_count - progress.pages_done) / rate;
  });

  /** Lo que ya salió de este documento, llamado por su nombre. */
  const units = $derived(job.report?.groups?.length ?? null);

  /**
   * Desde cuándo no llega noticia.
   *
   * Nunca es una alarma: es información. Una tanda de ocho páginas contra el
   * proveedor de OCR tarda sus segundos sin que pase nada malo, y decirlo es lo
   * que evita que parezca que el trabajo se ha muerto.
   */
  const silence = $derived(progress.silent_seconds ?? 0);
  const unitLabel = $derived(unitFor(job.report?.stats, units ?? 0));
  const warnings = $derived((progress.warnings ?? []).slice(0, 3));
  /** La luz del encabezado: en curso late; listo, verde; con fallo, rojo. */
  const luz = $derived(
    running ? 'live' : job.state === 'done' ? 'good' : job.state === 'failed' ? 'bad' : ''
  );

  /** El tono de la insignia de salud, con la `.pill` común. */
  const healthTone = $derived.by(() => {
    switch (progress.health) {
      case 'stalled':
      case 'failed':
        return 'pill-bad';
      case 'slow':
      case 'warning':
        return 'pill-warn';
      case 'done':
        return 'pill-good';
      default:
        return 'pill-neutral';
    }
  });

  const healthLabel = $derived.by(() => {
    switch (progress.health) {
      case 'stalled':
        return 'Bloqueado';
      case 'slow':
        return 'Lento';
      case 'warning':
        return 'Requiere atención';
      case 'done':
        return 'Listo';
      case 'failed':
        return 'Falló';
      default:
        return 'OK';
    }
  });
</script>

<section class="monitor panel" class:running>
  <header>
    <span class="status-dot {luz}" aria-hidden="true"></span>
    <h3 title={job.filename}>{job.filename}</h3>
    <span class="stage">{stageActivity(progress)}</span>
    {#if progress.health && progress.health !== 'ok'}
      <span class="pill {healthTone}">{healthLabel}</span>
    {/if}
    <RunControls jobId={job.id} runState={job.state} />
  </header>

  {#if running && (progress.detail || stageTotal)}
    <p class="stage-detail">
      <span>{progress.detail ?? stageActivity(progress)}</span>
      {#if stageTotal}
        <b>{stageDone} / {stageTotal}</b>
      {/if}
      {#if progress.stage_elapsed_seconds}
        <small>{progress.stage_elapsed_seconds.toFixed(0)} s en esta etapa</small>
      {/if}
    </p>
  {/if}

  {#if progress.health && progress.health !== 'ok'}
    <div class="health-strip" data-health={progress.health}>
      <span class="pill {healthTone}">{healthLabel}</span>
      {#if warnings.length}
        <ul class="warnings">
          {#each warnings as warning (warning)}
            <li class="pill pill-neutral">{warning}</li>
          {/each}
        </ul>
      {:else if running && silence >= SILENCE_THRESHOLD_SECONDS}
        <span class="silence">Sin novedades desde hace {Math.round(silence)} s</span>
      {/if}
    </div>
  {:else if warnings.length}
    <div class="health-strip" data-health="ok">
      <ul class="warnings">
        {#each warnings as warning (warning)}
          <li class="pill pill-neutral">{warning}</li>
        {/each}
      </ul>
    </div>
  {:else if running && silence >= SILENCE_THRESHOLD_SECONDS}
    <p class="silence">Sin novedades desde hace {Math.round(silence)} s</p>
  {/if}

  <!-- A meter, not a chart: one ratio against a known total. -->
  <div
    class="progress"
    role="progressbar"
    aria-valuenow={Math.round(percent)}
    aria-valuemin="0"
    aria-valuemax="100"
    aria-label="Avance del documento"
  >
    <div
      class="progress-fill"
      class:good={job.state === 'done'}
      style:width={`${visualPercent}%`}
    ></div>
  </div>

  <RunStats
    pagesDone={progress.pages_done}
    pagesTotal={progress.page_count}
    {units}
    {unitLabel}
    bytesTotal={job.bytes}
    bytesDone={bytesDone}
    rate={progress.pages_per_second}
    {elapsedSeconds}
    {remainingSeconds}
    settled={!running}
    stageDone={running ? stageDone : null}
    stageTotal={running ? stageTotal : null}
    consumo={progress.consumo ?? job.report?.consumo ?? null}
  />

  <PanelDeRendimiento
    paginasHechas={progress.pages_done}
    paginasTotal={progress.page_count}
    velocidad={progress.pages_per_second}
    segundos={elapsedSeconds}
    etapas={running ? [progress.stage] : []}
    procedencias={[progress.by_provenance]}
    revision={marcadasEnCinta(progress.ribbon)}
    fallidas={progress.failed_pages}
    consumo={progress.consumo ?? job.report?.consumo ?? null}
    vivo={running}
  />

  {#if progress.page_count}
    <PageRibbon ribbon={progress.ribbon} pageCount={progress.page_count} />
  {/if}
</section>

<style>
  /* La tarjeta es el `.panel` común; mientras corre, el filete lleva un tinte
     del acento: algo en curso. */
  .monitor {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .monitor.running {
    border-color: color-mix(in srgb, var(--accent) 30%, var(--hairline));
  }

  header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  h3 {
    overflow: hidden;
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 650;
    letter-spacing: -0.01em;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .stage-detail {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    margin: 0;
    font-size: var(--text-xs);
    color: var(--ink-2);
  }
  .stage-detail span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .stage-detail b,
  .stage-detail small {
    flex-shrink: 0;
    color: var(--muted);
  }
  /* La cifra en monoespaciada, para que no baile al avanzar; el texto de la
     etapa, en la letra de siempre. */
  .stage-detail b {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
  }
  /* La salud del documento: una insignia común y, al lado, los avisos. El
     filete toma el tono de la salud. */
  .health-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-pill);
    background: var(--plane);
    padding: var(--space-2) var(--space-3);
  }
  .health-strip[data-health='stalled'] {
    border-color: color-mix(in srgb, var(--critical) 50%, var(--hairline));
  }
  .health-strip[data-health='slow'],
  .health-strip[data-health='warning'] {
    border-color: color-mix(in srgb, var(--warning) 60%, var(--hairline));
  }
  .warnings {
    display: inline-flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .silence {
    margin: 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .stage {
    margin-left: auto;
    flex-shrink: 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }
</style>
