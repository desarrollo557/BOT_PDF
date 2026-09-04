<script lang="ts">
  import FolderTree from '$lib/components/FolderTree.svelte';
  import PageRibbon from '$lib/components/PageRibbon.svelte';
  import { jobStore } from '$lib/jobs.svelte';
  import { STAGE_LABELS } from '$lib/rungs';
  import type { FolderRun } from '$lib/types';

  interface Props {
    run: FolderRun;
  }

  let { run }: Props = $props();

  let stopping = $state(false);
  let forgetting = $state(false);
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

  /**
   * Quitar la tarjeta de la pantalla.
   *
   * No deshace nada: lo entregado sigue en la carpeta de destino y el archivo
   * conserva sus filas. Sólo está disponible cuando la carpeta ya terminó,
   * porque quitar una viva dejaría el trabajo corriendo sin nadie que informara.
   */
  async function forget() {
    forgetting = true;
    error = null;
    try {
      await jobStore.forgetRun(run.id);
    } catch (problem) {
      error = (problem as Error).message;
      forgetting = false;
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
    {:else}
      <button
        class="quitar"
        onclick={forget}
        disabled={forgetting}
        title="Quitar de la pantalla. Lo entregado se queda donde está."
      >
        {forgetting ? 'quitando…' : 'quitar'}
      </button>
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

  <!-- Which file it is on. Sequential by design, so there is exactly one.
       Una carpeta cerrada no está consumiendo nada, así que este bloque
       desaparece en vez de anunciar "ningún archivo abierto" para siempre. -->
  {#if active}
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
  {/if}

  {#if run.queue.length}
    <div class="column">
      <!-- Lo mismo dicho de dos maneras, porque no significa lo mismo. En una
           carpeta viva la cola es lo que va a procesarse; en una detenida es lo
           que se quedó sin procesar, y llamarlo "esperando turno" prometía un
           turno que no iba a llegar nunca. -->
      <span class="section-label" class:pendiente={!active}>
        {active
          ? `Esperando turno (${run.queue.length})`
          : `Quedaron sin procesar (${run.queue.length})`}
      </span>
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

  <!-- Lo que salió de la carpeta, con la forma en que está guardado: la
       carpeta contiene PDF y cada PDF contiene las unidades en que se partió.
       La lista plana de entregados decía qué archivos aparecieron en el
       destino, pero no de cuál habían salido, y eso había que reconstruirlo de
       memoria. -->
  <div class="column">
    <span class="section-label">Lo que produjo</span>
    <FolderTree {run} />
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
  /* Detener interrumpe un trabajo; quitar sólo despeja la pantalla. La primera
     se pinta como lo que es y la segunda no tiene por qué alarmar. */
  .head button.quitar:hover:not(:disabled) {
    border-color: var(--axis);
    color: var(--ink);
  }
  .head button:disabled {
    cursor: default;
    opacity: 0.55;
  }

  .section-label.pendiente {
    color: var(--warning);
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

</style>
