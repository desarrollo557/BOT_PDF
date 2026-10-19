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

<section class="monitor" class:running>
  <header>
    <span class="lamp" aria-hidden="true"></span>
    <h3 title={job.filename}>{job.filename}</h3>
    <span class="stage">{stageActivity(progress)}</span>
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

  {#if progress.health || warnings.length}
    <div class="health-strip" data-health={progress.health ?? 'ok'}>
      <span class="health-badge">{healthLabel}</span>
      {#if warnings.length}
        <ul class="warnings">
          {#each warnings as warning (warning)}
            <li>{warning}</li>
          {/each}
        </ul>
      {:else if running && silence >= SILENCE_THRESHOLD_SECONDS}
        <span class="silence">Sin novedades desde hace {Math.round(silence)} s</span>
      {/if}
    </div>
  {:else if running && silence >= SILENCE_THRESHOLD_SECONDS}
    <p class="silence">Sin novedades desde hace {Math.round(silence)} s</p>
  {/if}

  <!-- A meter, not a chart: one ratio against a known total. -->
  <div
    class="meter"
    role="progressbar"
    aria-valuenow={Math.round(percent)}
    aria-valuemin="0"
    aria-valuemax="100"
    aria-label="Avance del documento"
  >
    <div class="fill" style:width={`${visualPercent}%`}></div>
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
  .monitor {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    border: 1px solid var(--hairline);
    border-radius: var(--radius-lg);
    background: var(--surface-2);
    padding: 1.1rem 1.2rem;
    box-shadow: var(--shadow);
  }
  .monitor.running {
    border-color: color-mix(in oklab, var(--s1) 32%, var(--hairline));
  }

  header {
    display: flex;
    align-items: center;
    gap: 0.6rem;
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
    gap: 0.65rem;
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
  .health-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 0.85rem;
    padding: 0.5rem 0.7rem;
    border: 1px solid var(--hairline);
    border-radius: 999px;
    background: color-mix(in oklab, var(--surface-3) 80%, transparent);
  }
  .health-strip[data-health='stalled'] {
    border-color: color-mix(in oklab, var(--critical) 52%, var(--hairline));
  }
  .health-strip[data-health='slow'] {
    border-color: color-mix(in oklab, var(--warning) 60%, var(--hairline));
  }
  .health-strip[data-health='warning'] {
    border-color: color-mix(in oklab, var(--s2) 48%, var(--hairline));
  }
  .health-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.2rem 0.6rem;
    border-radius: 999px;
    font-size: var(--text-xs);
    font-weight: 700;
    letter-spacing: 0.02em;
    color: var(--ink-2);
    background: var(--surface-4);
  }
  .warnings {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin: 0;
    padding: 0;
    list-style: none;
    color: var(--ink-2);
    font-size: var(--text-xs);
  }
  .warnings li {
    padding: 0.2rem 0.45rem;
    border-radius: 999px;
    background: color-mix(in oklab, var(--surface-4) 80%, transparent);
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

  .lamp {
    width: 8px;
    height: 8px;
    flex-shrink: 0;
    border-radius: 50%;
    background: var(--good);
  }
  .running .lamp {
    background: var(--s1);
    box-shadow: 0 0 0 3px color-mix(in oklab, var(--s1) 18%, transparent);
    animation: breathe 1.6s ease-in-out infinite;
  }

  .meter {
    height: 8px;
    overflow: hidden;
    border-radius: var(--radius-pill);
    background: var(--grid);
  }
  .fill {
    height: 100%;
    /* Rounded data-end anchored to the baseline: the left edge stays square. */
    border-radius: 0 4px 4px 0;
    background: var(--s1);
    transition: width 0.3s ease-out;
  }

  @keyframes breathe {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.35;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .lamp {
      animation: none;
    }
  }
</style>
