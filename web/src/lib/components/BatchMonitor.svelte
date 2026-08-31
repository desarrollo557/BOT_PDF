<script lang="ts">
  import { onMount } from 'svelte';
  import PageRibbon from '$lib/components/PageRibbon.svelte';
  import ThroughputChart from '$lib/components/ThroughputChart.svelte';
  import { formatBytes, formatDuration } from '$lib/format';
  import { STAGE_LABELS } from '$lib/rungs';
  import type { Job } from '$lib/types';

  interface Props {
    name: string;
    jobs: Job[];
  }

  let { name, jobs }: Props = $props();

  const running = $derived(jobs.filter((job) => job.state === 'running'));
  const queued = $derived(jobs.filter((job) => job.state === 'queued'));
  const done = $derived(jobs.filter((job) => job.state === 'done'));
  const failed = $derived(jobs.filter((job) => job.state === 'failed'));

  const pagesTotal = $derived(jobs.reduce((sum, job) => sum + job.progress.page_count, 0));
  const pagesDone = $derived(jobs.reduce((sum, job) => sum + job.progress.pages_done, 0));
  const percent = $derived(jobs.length ? (100 * (done.length + failed.length)) / jobs.length : 0);
  const rate = $derived(running.reduce((sum, job) => sum + job.progress.pages_per_second, 0));
  const resolutions = $derived(
    jobs.reduce((sum, job) => sum + (job.report?.groups.length ?? 0), 0)
  );
  const settled = $derived(jobs.length > 0 && done.length + failed.length === jobs.length);

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
  const eta = $derived.by(() => {
    if (!rate || pagesDone >= pagesTotal) return null;
    const seconds = Math.round((pagesTotal - pagesDone) / rate);
    return formatDuration(seconds);
  });
</script>

<section class="monitor" class:settled>
  <header class="head">
    <span class="lamp" aria-hidden="true"></span>
    <h3>{name}</h3>
    <span class="counter tabular">{done.length + failed.length} / {jobs.length} documentos</span>
  </header>

  <div
    class="bar"
    role="progressbar"
    aria-valuenow={Math.round(percent)}
    aria-valuemin="0"
    aria-valuemax="100"
  >
    <div class="fill" style:width={`${percent}%`}></div>
  </div>

  <dl class="figures">
    <div><dt>Páginas</dt><dd class="tabular">{pagesDone} / {pagesTotal || '—'}</dd></div>
    <div><dt>Resoluciones</dt><dd class="tabular">{resolutions}</dd></div>
    <div>
      <dt>{settled ? 'Velocidad media' : 'Velocidad'}</dt>
      <dd class="tabular">{speed}</dd>
    </div>
    <div>
      <dt>Peso neto</dt>
      <dd class="tabular">{formatBytes(bytesTotal)}</dd>
    </div>
    <div>
      <dt>Leído</dt>
      <dd class="tabular">
        {formatBytes(bytesDone)}{#if byteRate}<span class="eta"> · {formatBytes(byteRate)}/s</span>{/if}
      </dd>
    </div>
    <div><dt>En cola</dt><dd class="tabular">{queued.length}</dd></div>
    <div>
      <dt>{settled ? 'Tardó' : 'Transcurrido'}</dt>
      <dd class="tabular">
        {elapsed}{#if eta && !settled}<span class="eta"> · faltan ~{eta}</span>{/if}
      </dd>
    </div>
  </dl>

  <div class="now">
    <ThroughputChart rate={rate} live={!settled} color="var(--s3)" />
    {#if heaviest && jobs.length > 1}
      <p class="footnote">
        El más pesado del lote es <b>{heaviest.filename}</b> con {formatBytes(heaviest.bytes)},
        el {bytesTotal ? ((100 * heaviest.bytes) / bytesTotal).toFixed(0) : 0} % del peso total.
      </p>
    {/if}
  </div>

  {#if running.length}
    <!-- The answer to "which file is it on right now". One block per worker,
         because eleven processes means eleven documents are open at once and a
         single "current file" would simply be untrue. -->
    <div class="now">
      <span class="section-label">Leyendo ahora ({running.length})</span>
      {#each running as job (job.id)}
        <article class="current">
          <div class="line">
            <span class="dot" aria-hidden="true"></span>
            <span class="file" title={job.filename}>{job.filename}</span>
            <span class="stage">{STAGE_LABELS[job.progress.stage] ?? job.progress.stage}</span>
            <span class="pages tabular">
              {job.progress.pages_done}/{job.progress.page_count || '?'}
            </span>
          </div>
          <div class="bar thin">
            <div class="fill" style:width={`${job.progress.percent}%`}></div>
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
      <span class="section-label">
        Cola del lote — {done.length} listos, {queued.length} esperando{failed.length
          ? `, ${failed.length} con error`
          : ''}
      </span>
      <ul>
        {#each jobs as job (job.id)}
          <li data-state={job.state} title={job.filename}>
            <span class="chip-dot" aria-hidden="true"></span>
            <span class="chip-name">{job.filename}</span>
          </li>
        {/each}
      </ul>
    </div>
  {/if}
</section>

<style>
  .monitor {
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
    border: 1px solid color-mix(in oklab, var(--s3) 30%, var(--hairline));
    border-radius: 14px;
    background: var(--surface-2);
    padding: 1.1rem 1.2rem;
    box-shadow: var(--shadow);
  }
  .monitor.settled {
    border-color: var(--hairline);
  }

  .head {
    display: flex;
    align-items: center;
    gap: 0.6rem;
  }
  .head h3 {
    margin: 0;
    font-size: 0.95rem;
    font-weight: 650;
    letter-spacing: -0.01em;
  }
  .counter {
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: 0.74rem;
    color: var(--muted);
  }

  .lamp {
    width: 8px;
    height: 8px;
    flex-shrink: 0;
    border-radius: 50%;
    background: var(--s3);
    box-shadow: 0 0 0 3px color-mix(in oklab, var(--s3) 18%, transparent);
    animation: breathe 1.6s ease-in-out infinite;
  }
  .settled .lamp {
    background: var(--good);
    animation: none;
  }

  .bar {
    height: 6px;
    overflow: hidden;
    border-radius: 999px;
    background: var(--grid);
  }
  .bar.thin {
    height: 3px;
  }
  .fill {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(
      90deg,
      var(--s3),
      color-mix(in oklab, var(--s3) 60%, var(--accent))
    );
    transition: width 0.3s ease-out;
  }

  .figures {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem 1.75rem;
    margin: 0;
  }
  .figures div {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .figures dt {
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .figures .eta {
    font-size: 0.76rem;
    color: var(--muted);
  }
  .figures dd {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 0.88rem;
    color: var(--ink);
  }

  .footnote {
    margin: 0.5rem 0 0;
    font-size: 0.74rem;
    color: var(--muted);
  }
  .footnote b {
    color: var(--ink-2);
  }

  .section-label {
    display: block;
    margin-bottom: 0.45rem;
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }

  .now {
    border-top: 1px solid var(--rule);
    padding-top: 0.8rem;
  }

  .current {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    border-radius: 10px;
    background: var(--plane);
    padding: 0.6rem 0.7rem;
  }
  .current + .current {
    margin-top: 0.45rem;
  }

  .line {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
  }
  .dot {
    width: 6px;
    height: 6px;
    flex-shrink: 0;
    border-radius: 50%;
    background: var(--s3);
    animation: breathe 1.2s ease-in-out infinite;
  }
  .file {
    overflow: hidden;
    font-size: 0.82rem;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .stage {
    flex-shrink: 0;
    font-size: 0.72rem;
    color: var(--ink-2);
  }
  .pages {
    margin-left: auto;
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--muted);
  }

  .queue {
    border-top: 1px solid var(--rule);
    padding-top: 0.8rem;
  }
  .queue ul {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .queue li {
    display: flex;
    max-width: 15rem;
    align-items: center;
    gap: 0.4rem;
    border: 1px solid var(--hairline);
    border-radius: 6px;
    background: var(--surface-1);
    padding: 0.15rem 0.45rem;
    font-size: 0.7rem;
    color: var(--muted);
  }
  .chip-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .chip-dot {
    width: 5px;
    height: 5px;
    flex-shrink: 0;
    border-radius: 50%;
    background: var(--axis);
  }
  [data-state='running'] {
    border-color: color-mix(in oklab, var(--s3) 45%, var(--hairline));
    color: var(--ink);
  }
  [data-state='running'] .chip-dot {
    background: var(--s3);
  }
  [data-state='done'] {
    color: var(--ink-2);
  }
  [data-state='done'] .chip-dot {
    background: var(--good);
  }
  [data-state='failed'] {
    border-color: color-mix(in oklab, var(--critical) 45%, var(--hairline));
    color: var(--critical);
  }
  [data-state='failed'] .chip-dot {
    background: var(--critical);
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
    .lamp,
    .dot {
      animation: none;
    }
  }
</style>
