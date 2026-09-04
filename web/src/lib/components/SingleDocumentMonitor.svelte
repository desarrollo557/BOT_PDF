<script lang="ts">
  import RunControls from '$lib/components/RunControls.svelte';
  import { onMount } from 'svelte';
  import PageRibbon from '$lib/components/PageRibbon.svelte';
  import ThroughputChart from '$lib/components/ThroughputChart.svelte';
  import { STAGE_LABELS } from '$lib/rungs';
  import { formatBytes, formatDuration } from '$lib/format';
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

  /** Bytes of the source read so far, apportioned by pages. */
  const bytesDone = $derived(job.bytes ? Math.round((job.bytes * percent) / 100) : 0);

  const eta = $derived.by(() => {
    const rate = progress.pages_per_second;
    if (!rate || !progress.page_count || progress.pages_done >= progress.page_count) return null;
    return formatDuration((progress.page_count - progress.pages_done) / rate);
  });
</script>

<section class="monitor" class:running>
  <header>
    <span class="lamp" aria-hidden="true"></span>
    <h3 title={job.filename}>{job.filename}</h3>
    <span class="stage">{STAGE_LABELS[progress.stage] ?? progress.stage}</span>
    <RunControls jobId={job.id} runState={job.state} />
  </header>

  <!-- A meter, not a chart: one ratio against a known total. -->
  <div
    class="meter"
    role="progressbar"
    aria-valuenow={Math.round(percent)}
    aria-valuemin="0"
    aria-valuemax="100"
    aria-label="Avance del documento"
  >
    <div class="fill" style:width={`${percent}%`}></div>
  </div>

  <!-- Single current values: stat tiles, never a one-bar chart. -->
  <dl class="tiles">
    <div>
      <dt>Tiempo</dt>
      <dd class="hero tabular">{formatDuration(elapsedSeconds)}</dd>
      <dd class="note">{eta ? `faltan ~${eta}` : running ? 'calculando…' : 'total'}</dd>
    </div>
    <div>
      <dt>Almacenamiento</dt>
      <dd class="hero tabular">{formatBytes(job.bytes)}</dd>
      <dd class="note">
        {job.bytes ? `${formatBytes(bytesDone)} leídos` : 'tamaño no registrado'}
      </dd>
    </div>
    <div>
      <dt>Páginas</dt>
      <dd class="hero tabular">{progress.pages_done}<span>/{progress.page_count || '?'}</span></dd>
      <dd class="note">{percent.toFixed(0)} % del documento</dd>
    </div>
    <div>
      <dt>Velocidad</dt>
      <dd class="hero tabular">{progress.pages_per_second.toFixed(1)}<span> p/s</span></dd>
      <dd class="note">
        {elapsedSeconds > 0 && job.bytes
          ? `${formatBytes(job.bytes / elapsedSeconds)}/s`
          : 'páginas por segundo'}
      </dd>
    </div>
  </dl>

  <ThroughputChart rate={progress.pages_per_second} live={running} />

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
    border-radius: 14px;
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
    font-size: 0.95rem;
    font-weight: 650;
    letter-spacing: -0.01em;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .stage {
    margin-left: auto;
    flex-shrink: 0;
    font-size: 0.74rem;
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
    border-radius: 999px;
    background: var(--grid);
  }
  .fill {
    height: 100%;
    /* Rounded data-end anchored to the baseline: the left edge stays square. */
    border-radius: 0 4px 4px 0;
    background: var(--s1);
    transition: width 0.3s ease-out;
  }

  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr));
    gap: 0.9rem 1.5rem;
    margin: 0;
  }
  .tiles div {
    display: flex;
    flex-direction: column;
    gap: 1px;
    border-left: 2px solid var(--rule);
    padding-left: 0.7rem;
  }
  .tiles dt {
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .tiles dd {
    margin: 0;
  }
  .hero {
    font-size: 1.35rem;
    font-weight: 550;
    line-height: 1.2;
    letter-spacing: -0.02em;
  }
  .hero span {
    font-size: 0.8rem;
    font-weight: 400;
    color: var(--muted);
  }
  .note {
    font-size: 0.72rem;
    color: var(--ink-2);
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
