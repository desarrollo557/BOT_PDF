<script lang="ts">
  import { consoleLog } from '$lib/console.svelte';
  import { formatBytes, formatDuration } from '$lib/format';
  import { jobStore } from '$lib/jobs.svelte';
  import { reports, type Completion } from '$lib/report.svelte';
  import { RUNGS, UNREADABLE } from '$lib/rungs';

  interface Props {
    completion: Completion;
  }

  let { completion }: Props = $props();

  const KIND: Record<Completion['kind'], string> = {
    documento: 'Documento procesado',
    lote: 'Lote procesado',
    carpeta: 'Carpeta procesada',
    tanda: 'Ejecución completa'
  };

  const clean = $derived(completion.failedDocuments === 0 && completion.reviewItems === 0);

  /**
   * Cerrar el informe deja la pantalla lista para el siguiente lote. Siempre.
   *
   * Un operador que procesa caja tras caja no quiere empezar la siguiente con
   * las fichas de la anterior debajo: cerrar el informe es la señal de que ya
   * miró lo que pasó. Se olvidan los trabajos terminados, que es distinto de
   * borrarlos -- el trabajo queda en el archivo, este informe se vuelve a abrir
   * desde ahí, y lo que quedó por revisar sigue listado en Revisión, que se
   * guarda su propia copia justamente para que limpiar no le quite nada.
   */
  async function dismiss(): Promise<void> {
    reports.close();
    try {
      await jobStore.clear();
      // Y si no queda ninguna carpeta en marcha, se borran también las rutas
      // del formulario. No hace falta recordar si se marcó "Vigilar la
      // carpeta": una carpeta vigilada sigue viva en `activeRuns` esperando
      // archivos nuevos, y una que terminó no. El estado lo dice mejor que la
      // casilla, porque también acierta cuando la vigilancia se detuvo a mano.
      if (jobStore.activeRuns.length === 0) jobStore.resetWorkspace();
    } catch (problem) {
      // Que no se pueda limpiar no es motivo para dejar el informe abierto: ya
      // se cerró, y el motivo queda escrito donde se miran estas cosas.
      consoleLog.push(
        'WARN',
        `no se pudo limpiar la pantalla: ${(problem as Error).message}`,
        'warn'
      );
    }
  }
  const rate = $derived(
    completion.elapsedSeconds >= 1 ? completion.pages / completion.elapsedSeconds : 0
  );

  /** Rungs that actually answered a page, in cascade order. */
  const rungs = $derived(
    [...RUNGS, UNREADABLE]
      .map((rung) => ({ rung, count: completion.provenance[rung.key] ?? 0 }))
      .filter((entry) => entry.count > 0)
  );
  const counted = $derived(rungs.reduce((sum, entry) => sum + entry.count, 0));

  /**
   * The report is one screen with sections behind tabs, not one long scroll.
   *
   * A single file produces a page worth of report; a folder of eighty produces
   * eighty rows of documents and several hundred resolutions. Stacking all of
   * it vertically buries the four numbers anyone actually opens this for, so
   * the totals stay pinned at the top and everything else waits behind a tab.
   */
  const tabs = $derived(
    [
      { id: 'resumen', label: 'Resumen', count: 0 },
      { id: 'unidades', label: 'Unidades', count: completion.parts?.length ?? 0 },
      { id: 'documentos', label: 'Documentos', count: completion.items.length },
      { id: 'resoluciones', label: 'Resoluciones', count: completion.codes.length }
    ].filter((tab) => tab.id === 'resumen' || tab.count > 0)
  );

  let tab = $state('resumen');
  /** Narrows the resolution list, which is the only section that gets long. */
  let filter = $state('');

  const shown = $derived.by(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return completion.codes;
    return completion.codes.filter(
      (entry) =>
        entry.code.toLowerCase().includes(needle) ||
        (entry.title ?? '').toLowerCase().includes(needle) ||
        entry.document.toLowerCase().includes(needle)
    );
  });

  const failed = $derived(completion.items.filter((item) => item.state === 'failed'));

  function when(at: number): string {
    return new Date(at).toLocaleString('es', { dateStyle: 'medium', timeStyle: 'medium' });
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
  class="scrim"
  role="presentation"
  onclick={(event) => {
    if (event.target === event.currentTarget) void dismiss();
  }}
>
  <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="informe-titulo">
    <header>
      <div class="who">
        <span class="badge" class:clean>{KIND[completion.kind]}</span>
        <h2 id="informe-titulo">{completion.title}</h2>
      </div>
      <div class="meta">
        {#if completion.operator}<span class="by">{completion.operator}</span>{/if}
        <time>{when(completion.finishedAt)}</time>
        <button class="close" onclick={() => void dismiss()} aria-label="Cerrar">✕</button>
      </div>
    </header>

    <!-- Siempre a la vista: es lo que se viene a mirar. -->
    <dl class="tiles">
      <div>
        <dt>Documentos</dt>
        <dd class="tabular" class:warn={completion.failedDocuments > 0}>
          {completion.documents}
        </dd>
        <dd class="note">
          {completion.failedDocuments
            ? `${completion.failedDocuments} con error`
            : 'todos completos'}
        </dd>
      </div>
      <div>
        <dt>Resoluciones</dt>
        <dd class="tabular">{completion.resolutions}</dd>
        <dd class="note">archivos generados</dd>
      </div>
      <div>
        <dt>Páginas</dt>
        <dd class="tabular">{completion.pages}</dd>
        <dd class="note">{rate ? `${rate.toFixed(1)} p/s` : 'leídas'}</dd>
      </div>
      <div>
        <dt>Peso neto</dt>
        <dd class="tabular">{formatBytes(completion.bytes)}</dd>
        <dd class="note">de los PDF de origen</dd>
      </div>
      <div>
        <dt>Tardó</dt>
        <dd class="tabular">{formatDuration(completion.elapsedSeconds)}</dd>
        <dd class="note">de reloj</dd>
      </div>
      <div>
        <dt>Requiere revisión</dt>
        <dd class="tabular" class:warn={completion.reviewItems > 0}>{completion.reviewItems}</dd>
        <dd class="note">{completion.reviewItems ? 'páginas' : 'sin pendientes'}</dd>
      </div>
    </dl>

    {#if tabs.length > 1}
      <nav class="tabs">
        {#each tabs as item (item.id)}
          <button class:current={tab === item.id} onclick={() => (tab = item.id)}>
            {item.label}
            {#if item.count}<span class="count tabular">{item.count}</span>{/if}
          </button>
        {/each}
      </nav>
    {/if}

    <div class="body">
      {#if tab === 'resumen'}
        {#if completion.destination}
          <p class="destination">
            Entregado en <b>{completion.destination}</b>
            {#if completion.delivered}· {completion.delivered} archivos{/if}
          </p>
        {/if}

        {#if failed.length}
          <section class="trouble">
            <h3>No se pudieron procesar</h3>
            <ul class="errors">
              {#each failed as item (item.jobId)}
                <li><b>{item.filename}</b><span>{item.error ?? 'error desconocido'}</span></li>
              {/each}
            </ul>
          </section>
        {/if}

        {#if counted}
          <!-- Part-to-whole across the cascade: a stacked bar, each segment
               labelled, with a 2px surface gap rather than a border. -->
          <section>
            <h3>Cómo se leyó cada página</h3>
            <div class="stack" role="img" aria-label="Reparto de páginas por rung del cascade">
              {#each rungs as entry (entry.rung.key)}
                <span
                  class="segment"
                  style:width={`${(100 * entry.count) / counted}%`}
                  style:background={entry.rung.color}
                  title={`${entry.rung.label}: ${entry.count}`}
                ></span>
              {/each}
            </div>
            <ul class="legend">
              {#each rungs as entry (entry.rung.key)}
                <li>
                  <span class="swatch" style:background={entry.rung.color}></span>
                  <span>{entry.rung.label}</span>
                  <b class="tabular">{entry.count}</b>
                  <span class="pct tabular">{((100 * entry.count) / counted).toFixed(0)} %</span>
                </li>
              {/each}
            </ul>
            <p class="footnote">
              {completion.escalated} página{completion.escalated === 1 ? '' : 's'} llegaron al
              modelo de visión ({counted
                ? ((100 * completion.escalated) / counted).toFixed(1)
                : '0.0'} %) · {completion.repairs} corrección{completion.repairs === 1
                ? ''
                : 'es'} de OCR · {completion.quarantine} en cuarentena
            </p>
          </section>
        {/if}
      {:else if tab === 'unidades'}
        <!-- El desglose de una tanda: qué fue cada cosa que corrió. -->
        <ul class="units">
          {#each completion.parts ?? [] as part (part.id)}
            <li>
              <span class="tag">{KIND[part.kind]}</span>
              <span class="name" title={part.title}>{part.title}</span>
              <span class="num tabular">{part.resolutions} res.</span>
              <span class="num tabular">{part.pages} pág.</span>
              <span class="num tabular">{formatDuration(part.elapsedSeconds)}</span>
              {#if part.failedDocuments}
                <span class="num bad tabular">{part.failedDocuments} error</span>
              {/if}
            </li>
          {/each}
        </ul>
      {:else if tab === 'documentos'}
        <table>
          <thead>
            <tr>
              <th>Archivo</th>
              <th>Páginas</th>
              <th>Resoluciones</th>
              <th>Tamaño</th>
              <th>Revisión</th>
            </tr>
          </thead>
          <tbody>
            {#each completion.items as item (item.jobId)}
              <tr class:failed={item.state === 'failed'}>
                <td title={item.error ?? item.filename}>{item.filename}</td>
                <td class="num tabular">{item.pages || '—'}</td>
                <td class="num tabular">{item.resolutions || '—'}</td>
                <td class="num tabular">{formatBytes(item.bytes)}</td>
                <td class="num tabular">{item.review || '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else if tab === 'resoluciones'}
        <input
          class="search"
          bind:value={filter}
          placeholder="Filtrar por número, título o documento"
          spellcheck="false"
        />
        <ul class="codes">
          {#each shown as entry (entry.document + entry.code)}
            <li>
              <span class="code">{entry.code}</span>
              <span class="title">{entry.title ?? 'sin título'}</span>
              <span class="from" title={entry.document}>{entry.document}</span>
              <span class="size tabular">{entry.size} pág.</span>
            </li>
          {/each}
          {#if !shown.length}
            <li class="empty">Ninguna resolución coincide con la búsqueda.</li>
          {/if}
        </ul>
      {/if}
    </div>

    <footer>
      <!--
        Se dice qué hace el botón antes de pulsarlo. Una pantalla que se vacía
        sola al cerrar un aviso se lee como una pérdida, aunque no lo sea.
      -->
      <span class="note">
        Al cerrar se limpia la pantalla. El trabajo queda en el archivo y este informe
        se vuelve a abrir desde ahí{#if !clean}, y lo pendiente sigue en Revisión{/if}.
      </span>
      <a href="/archivo" onclick={() => void dismiss()}>Ver en el archivo</a>
      {#if completion.reviewItems}
        <a class="warn" href="/revision" onclick={() => void dismiss()}>
          Revisar {completion.reviewItems} páginas
        </a>
      {/if}
      <button onclick={() => void dismiss()}>Cerrar</button>
    </footer>
  </div>
</div>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 80;
    display: grid;
    place-items: center;
    background: rgb(0 0 0 / 0.45);
    padding: 1.5rem;
    backdrop-filter: blur(3px);
    animation: fade 0.16s ease-out;
  }

  .sheet {
    display: flex;
    width: min(72rem, 100%);
    max-height: min(88dvh, 56rem);
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--hairline);
    border-radius: 16px;
    background: var(--surface-2);
    box-shadow: 0 24px 70px rgb(0 0 0 / 0.35);
    animation: rise 0.18s ease-out;
  }

  header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem 1rem;
    padding: 1rem 1.25rem 0.75rem;
  }
  .who {
    display: flex;
    min-width: 0;
    flex: 1;
    flex-direction: column;
    gap: 0.25rem;
  }
  .meta {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  .badge {
    align-self: flex-start;
    border: 1px solid color-mix(in oklab, var(--warning) 45%, var(--hairline));
    border-radius: 999px;
    padding: 0.1rem 0.6rem;
    font-family: var(--font-mono);
    font-size: 0.64rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--warning);
  }
  .badge.clean {
    border-color: color-mix(in oklab, var(--good) 45%, var(--hairline));
    color: var(--good);
  }
  header h2 {
    overflow: hidden;
    margin: 0;
    font-size: 1.15rem;
    font-weight: 650;
    letter-spacing: -0.015em;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .by {
    border-radius: 999px;
    background: var(--accent-soft);
    padding: 0.05rem 0.5rem;
    font-size: 0.72rem;
    color: var(--accent);
  }
  header time {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--muted);
  }
  .close {
    border: 0;
    background: none;
    padding: 0 0 0 0.25rem;
    font-size: 0.9rem;
    color: var(--muted);
    cursor: pointer;
  }
  .close:hover {
    color: var(--ink);
  }

  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
    gap: 0.9rem 1.25rem;
    margin: 0;
    padding: 0.35rem 1.25rem 1rem;
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
    font-size: 1.35rem;
    font-weight: 550;
    line-height: 1.2;
    letter-spacing: -0.02em;
  }
  .tiles dd.warn {
    color: var(--warning);
  }
  .tiles .note {
    font-size: 0.72rem;
    font-weight: 400;
    letter-spacing: 0;
    color: var(--ink-2);
  }

  .tabs {
    display: flex;
    gap: 0.15rem;
    border-bottom: 1px solid var(--hairline);
    padding: 0 1rem;
  }
  .tabs button {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    border: 0;
    border-bottom: 2px solid transparent;
    background: none;
    padding: 0.5rem 0.7rem;
    font: inherit;
    font-size: 0.82rem;
    color: var(--muted);
    cursor: pointer;
    transition:
      color 0.15s,
      border-color 0.15s;
  }
  .tabs button:hover {
    color: var(--ink-2);
  }
  .tabs button.current {
    border-bottom-color: var(--accent);
    color: var(--ink);
  }
  .count {
    border-radius: 999px;
    background: var(--plane);
    padding: 0.02rem 0.4rem;
    font-family: var(--font-mono);
    font-size: 0.68rem;
    color: var(--muted);
  }

  .body {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 1.5rem;
    overflow-y: auto;
    padding: 1.25rem;
  }

  .destination {
    margin: 0;
    border-left: 2px solid var(--s4);
    padding-left: 0.7rem;
    font-size: 0.82rem;
    color: var(--ink-2);
  }
  .destination b {
    font-family: var(--font-mono);
    font-size: 0.76rem;
  }

  section h3 {
    margin: 0 0 0.55rem;
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .trouble h3 {
    color: var(--critical);
  }
  .errors {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .errors li {
    display: flex;
    flex-wrap: wrap;
    gap: 0.15rem 0.6rem;
    border-left: 2px solid var(--critical);
    padding-left: 0.7rem;
    font-size: 0.8rem;
  }
  .errors span {
    font-family: var(--font-mono);
    font-size: 0.74rem;
    color: var(--muted);
  }

  .stack {
    display: flex;
    height: 10px;
    overflow: hidden;
    border-radius: 5px;
    /* A surface gap between segments, never a border around them. */
    gap: 2px;
  }
  .segment {
    height: 100%;
  }

  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem 1.25rem;
    margin: 0.6rem 0 0;
    padding: 0;
    list-style: none;
  }
  .legend li {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.78rem;
    color: var(--ink-2);
  }
  .swatch {
    width: 9px;
    height: 9px;
    border-radius: 2px;
  }
  .legend b {
    font-family: var(--font-mono);
    font-weight: 600;
    color: var(--ink);
  }
  .pct {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--muted);
  }

  .footnote {
    margin: 0.6rem 0 0;
    font-size: 0.75rem;
    color: var(--muted);
  }

  .units {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .units li {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    border-radius: 7px;
    padding: 0.4rem 0.55rem;
    font-size: 0.82rem;
  }
  .units li:nth-child(odd) {
    background: var(--plane);
  }
  .tag {
    flex-shrink: 0;
    width: 9.5rem;
    font-size: 0.66rem;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .units .name {
    overflow: hidden;
    flex: 1;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .bad {
    color: var(--critical);
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
  }
  thead th {
    padding: 0 0.5rem 0.4rem 0;
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-align: left;
    text-transform: uppercase;
    color: var(--muted);
  }
  tbody tr {
    border-top: 1px solid var(--hairline);
  }
  tbody td {
    overflow: hidden;
    max-width: 22rem;
    padding: 0.4rem 0.5rem 0.4rem 0;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .num {
    flex-shrink: 0;
    text-align: right;
    font-family: var(--font-mono);
    font-size: 0.76rem;
    color: var(--ink-2);
  }
  tr.failed td {
    color: var(--critical);
  }

  .search {
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: var(--plane);
    padding: 0.4rem 0.65rem;
    font-family: var(--font-mono);
    font-size: 0.76rem;
    color: inherit;
    outline: none;
  }
  .search:focus {
    border-color: var(--accent);
  }

  .codes {
    display: flex;
    flex-direction: column;
    gap: 1px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .codes li {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    border-radius: 5px;
    padding: 0.22rem 0.4rem;
    font-size: 0.8rem;
  }
  .codes li:nth-child(odd) {
    background: var(--plane);
  }
  .code {
    flex-shrink: 0;
    width: 6.5rem;
    font-family: var(--font-mono);
    font-size: 0.76rem;
  }
  .codes .title {
    overflow: hidden;
    flex: 1;
    color: var(--ink-2);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .from {
    overflow: hidden;
    max-width: 14rem;
    flex-shrink: 0;
    font-size: 0.72rem;
    color: var(--muted);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .size {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--muted);
  }
  .empty {
    color: var(--muted);
  }

  /* La explicación empuja los botones a la derecha y se lee antes que ellos. */
  .note {
    flex: 1;
    color: var(--muted);
    font-size: 0.78rem;
    line-height: 1.35;
  }

  footer {
    display: flex;
    align-items: center;
    gap: 1rem;
    border-top: 1px solid var(--hairline);
    padding: 0.85rem 1.25rem;
  }
  footer a {
    font-size: 0.83rem;
    color: var(--accent);
    text-decoration: none;
  }
  footer a:hover {
    text-decoration: underline;
  }
  footer a.warn {
    color: var(--warning);
  }
  footer button {
    margin-left: auto;
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: transparent;
    padding: 0.35rem 0.9rem;
    font: inherit;
    font-size: 0.82rem;
    color: var(--ink-2);
    cursor: pointer;
  }
  footer button:hover {
    border-color: var(--accent);
    color: var(--accent);
  }

  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .scrim,
    .sheet {
      animation: none;
    }
  }
</style>
