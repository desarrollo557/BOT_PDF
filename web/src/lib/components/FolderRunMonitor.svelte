<script lang="ts">
  import PageRibbon from '$lib/components/PageRibbon.svelte';
  import { jobStore } from '$lib/jobs.svelte';
  import { STAGE_LABELS } from '$lib/rungs';
  import type { FolderRun } from '$lib/types';

  interface Props {
    run: FolderRun;
  }

  let { run }: Props = $props();

  let stopping = $state(false);
  let error = $state<string | null>(null);

  const STATES: Record<string, string> = {
    scanning: 'Explorando la carpeta',
    processing: 'Procesando',
    watching: 'Vigilando — esperando archivos nuevos',
    done: 'Terminado',
    stopped: 'Detenido',
    failed: 'Falló'
  };

  const active = $derived(['scanning', 'processing', 'watching'].includes(run.state));
  /** The document the runner has open right now, if it is still on screen. */
  const job = $derived(run.current_job_id ? jobStore.get(run.current_job_id) : undefined);

  function clock(at: string): string {
    const parsed = Date.parse(at);
    if (Number.isNaN(parsed)) return '';
    return new Date(parsed).toLocaleTimeString('es', { hour12: false });
  }

  async function stop() {
    stopping = true;
    error = null;
    try {
      await jobStore.stopFolder(run.id);
    } catch (problem) {
      error = (problem as Error).message;
    } finally {
      stopping = false;
    }
  }
</script>

<section class="run" data-state={run.state}>
  <header class="head">
    <span class="lamp" aria-hidden="true"></span>
    <div class="titles">
      <b>{STATES[run.state] ?? run.state}</b>
      <small class="paths">
        <span title={run.source}>{run.source}</span>
        <span class="arrow" aria-hidden="true">→</span>
        <span title={run.destination}>{run.destination}</span>
      </small>
    </div>
    {#if active}
      <button onclick={stop} disabled={stopping}>{stopping ? 'deteniendo…' : 'detener'}</button>
    {/if}
  </header>

  {#if run.error}
    <p class="error">{run.error}</p>
  {/if}
  {#if error}
    <p class="error">{error}</p>
  {/if}

  <dl class="figures">
    <div><dt>Procesados</dt><dd class="tabular">{run.processed}</dd></div>
    <div><dt>Entregados</dt><dd class="tabular">{run.delivered}</dd></div>
    <div><dt>Resoluciones</dt><dd class="tabular">{run.resolutions}</dd></div>
    <div><dt>En cola</dt><dd class="tabular">{run.queue.length}</dd></div>
    <div>
      <dt>Con error</dt>
      <dd class="tabular" class:bad={run.failed > 0}>{run.failed}</dd>
    </div>
  </dl>

  <!-- Which file it is on. Sequential by design, so there is exactly one. -->
  <div class="column">
    <span class="section-label">Consumiendo ahora</span>
    {#if run.current}
      <article class="current">
        <div class="line">
          <span class="dot" aria-hidden="true"></span>
          <span class="file" title={run.current}>{run.current}</span>
          {#if job}
            <span class="stage">{STAGE_LABELS[job.progress.stage] ?? job.progress.stage}</span>
            <span class="pages tabular">
              {job.progress.pages_done}/{job.progress.page_count || '?'}
            </span>
          {/if}
        </div>
        {#if job?.progress.page_count}
          <div class="bar">
            <div class="fill" style:width={`${job.progress.percent}%`}></div>
          </div>
          <PageRibbon ribbon={job.progress.ribbon} pageCount={job.progress.page_count} />
        {/if}
      </article>
    {:else}
      <p class="idle">
        {run.state === 'watching'
          ? 'Ningún archivo pendiente. La carpeta queda bajo vigilancia.'
          : 'Ningún archivo abierto.'}
      </p>
    {/if}
  </div>

  {#if run.queue.length}
    <div class="column">
      <span class="section-label">Esperando turno ({run.queue.length})</span>
      <ul class="queue">
        {#each run.queue.slice(0, 40) as name (name)}
          <li title={name}>{name}</li>
        {/each}
        {#if run.queue.length > 40}
          <li class="more">+{run.queue.length - 40}</li>
        {/if}
      </ul>
    </div>
  {/if}

  <!-- The other half of what was asked for: seeing the files leave. -->
  <div class="column">
    <span class="section-label">Entregados en el destino ({run.delivered})</span>
    {#if run.deliveries.length}
      <ul class="deliveries">
        {#each run.deliveries as delivery (delivery.file_name + delivery.at)}
          <li>
            <span class="at tabular">{clock(delivery.at)}</span>
            <span class="out" aria-hidden="true">↳</span>
            <span class="delivered" title={delivery.file_name}>{delivery.file_name}</span>
            <span class="from" title={delivery.source_document}>de {delivery.source_document}</span>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="idle">Todavía no se entregó ningún archivo.</p>
    {/if}
  </div>
</section>

<style>
  .run {
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
    border: 1px solid color-mix(in oklab, var(--s4) 32%, var(--hairline));
    border-radius: 14px;
    background: var(--surface-2);
    padding: 1.1rem 1.2rem;
    box-shadow: var(--shadow);
  }
  [data-state='done'],
  [data-state='stopped'] {
    border-color: var(--hairline);
  }
  [data-state='failed'] {
    border-color: color-mix(in oklab, var(--critical) 45%, var(--hairline));
  }

  .head {
    display: flex;
    align-items: flex-start;
    gap: 0.6rem;
  }
  .lamp {
    margin-top: 0.3rem;
    width: 8px;
    height: 8px;
    flex-shrink: 0;
    border-radius: 50%;
    background: var(--axis);
  }
  [data-state='processing'] .lamp,
  [data-state='scanning'] .lamp {
    background: var(--s4);
    box-shadow: 0 0 0 3px color-mix(in oklab, var(--s4) 18%, transparent);
    animation: breathe 1.6s ease-in-out infinite;
  }
  [data-state='watching'] .lamp {
    background: var(--s4);
    animation: breathe 3s ease-in-out infinite;
  }
  [data-state='done'] .lamp {
    background: var(--good);
  }
  [data-state='failed'] .lamp {
    background: var(--critical);
  }

  .titles {
    display: flex;
    min-width: 0;
    flex-direction: column;
  }
  .titles b {
    font-size: 0.9rem;
    font-weight: 650;
  }
  .paths {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 0.4rem;
    font-family: var(--font-mono);
    font-size: 0.68rem;
    color: var(--muted);
  }
  .paths span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .arrow {
    flex-shrink: 0;
    color: var(--s4);
  }

  .head button {
    margin-left: auto;
    flex-shrink: 0;
    border: 1px solid var(--hairline);
    border-radius: 7px;
    background: transparent;
    padding: 0.2rem 0.6rem;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--muted);
    cursor: pointer;
  }
  .head button:hover:not(:disabled) {
    border-color: var(--critical);
    color: var(--critical);
  }

  .error {
    margin: 0;
    border-left: 2px solid var(--critical);
    padding-left: 0.6rem;
    font-family: var(--font-mono);
    font-size: 0.75rem;
    color: var(--critical);
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
  .figures dd {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 0.88rem;
    color: var(--ink);
  }
  .figures dd.bad {
    color: var(--critical);
  }

  .column {
    border-top: 1px solid var(--rule);
    padding-top: 0.8rem;
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

  .current {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    border-radius: 10px;
    background: var(--plane);
    padding: 0.6rem 0.7rem;
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
    background: var(--s4);
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

  .bar {
    height: 3px;
    overflow: hidden;
    border-radius: 999px;
    background: var(--grid);
  }
  .fill {
    height: 100%;
    border-radius: 999px;
    background: var(--s4);
    transition: width 0.3s ease-out;
  }

  .idle {
    margin: 0;
    font-size: 0.78rem;
    color: var(--muted);
  }

  .queue {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .queue li {
    max-width: 14rem;
    overflow: hidden;
    border: 1px solid var(--hairline);
    border-radius: 6px;
    background: var(--surface-1);
    padding: 0.12rem 0.45rem;
    font-size: 0.7rem;
    color: var(--muted);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .queue .more {
    border-style: dashed;
  }

  .deliveries {
    display: flex;
    max-height: 15rem;
    flex-direction: column;
    gap: 1px;
    margin: 0;
    overflow-y: auto;
    padding: 0;
    list-style: none;
  }
  .deliveries li {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    border-radius: 5px;
    padding: 0.15rem 0.35rem;
    font-size: 0.74rem;
  }
  .deliveries li:nth-child(odd) {
    background: var(--plane);
  }
  .at {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 0.68rem;
    color: var(--axis);
  }
  .out {
    flex-shrink: 0;
    color: var(--good);
  }
  .delivered {
    overflow: hidden;
    font-family: var(--font-mono);
    font-size: 0.72rem;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--ink);
  }
  .from {
    margin-left: auto;
    flex-shrink: 0;
    font-size: 0.68rem;
    color: var(--muted);
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
