<script lang="ts">
  /**
   * El archivo visto por documento de origen: qué PDF se procesó, cuándo y con
   * qué resultado.
   *
   * Es la lupa ancha de la pantalla de Archivo. Todo lo que decide qué se ve
   * -- filtrar, ordenar, agrupar por día, contar lo seleccionado -- vive en
   * `archive.svelte.ts` y llega ya resuelto; aquí sólo se dibuja.
   */
  import { type Day, type Filters, type Sort } from '$lib/archive.svelte';
  import type { Entry } from '$lib/components/ProcessedCard.svelte';
  import ProcessedCard from '$lib/components/ProcessedCard.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import { formatBytes } from '$lib/format';
  import { reports } from '$lib/report.svelte';
  import BarraDeSeleccion from './BarraDeSeleccion.svelte';
  import FiltrosDelArchivo from './FiltrosDelArchivo.svelte';

  interface Totales {
    documents: number;
    resolutions: number;
    pages: number;
    bytes: number;
    review: number;
  }

  interface Seleccionados {
    documents: number;
    resolutions: number;
    pages: number;
  }

  interface Resultado {
    deleted: number;
    rows: number;
    failed: { job_id: string; reason: string }[];
  }

  let {
    filters = $bindable(),
    sort = $bindable(),
    bulkOutcome = $bindable(),
    everything,
    shown,
    days,
    totals,
    narrowed,
    people,
    hayEnVivo = false,
    selected,
    allPicked,
    pickedTotals,
    bulkBusy = false,
    historyCount,
    historyTotal,
    nameOf,
    onpick,
    onpickall,
    onclearselection,
    onremoveselected,
    onclearscreen,
    onchange
  }: {
    filters: Filters;
    sort: Sort;
    bulkOutcome: Resultado | null;
    /** Todo lo que hay, para poder decir «de N en total» cuando se filtra. */
    everything: Entry[];
    shown: Entry[];
    days: Day[];
    totals: Totales;
    narrowed: boolean;
    people: string[];
    hayEnVivo?: boolean;
    selected: Set<string>;
    allPicked: boolean;
    pickedTotals: Seleccionados;
    bulkBusy?: boolean;
    /** Cuántos documentos del archivo caben en esta página y cuántos hay. */
    historyCount: number;
    historyTotal: number;
    nameOf: (jobId: string) => string;
    onpick: (jobId: string) => void;
    onpickall: () => void;
    onclearselection: () => void;
    onremoveselected: () => void;
    onclearscreen: () => void;
    onchange: () => void;
  } = $props();
</script>

<!-- Totals for what is actually on screen, so narrowing the filters answers
     "how much is this" without anybody adding up cards. -->
<section class="summary">
  <StatTile
    label={narrowed ? 'Documentos filtrados' : 'Documentos'}
    value={totals.documents}
    note={narrowed ? `de ${everything.length} en total` : 'procesados'}
  />
  <StatTile label="Resoluciones" value={totals.resolutions} note="archivos generados" />
  <StatTile label="Páginas" value={totals.pages} />
  <StatTile label="Peso neto" value={formatBytes(totals.bytes)} note="de los PDF de origen" />
  <StatTile
    label="Requiere revisión"
    value={totals.review}
    tone={totals.review ? 'warning' : 'good'}
    note={totals.review ? 'ver en Revisión' : 'sin pendientes'}
  />
</section>

<FiltrosDelArchivo
  bind:filters
  bind:sort
  {people}
  {narrowed}
  {hayEnVivo}
  onclear={onclearscreen}
/>

{#if reports.history.length}
  <details class="runs">
    <summary>Informes de ejecución ({reports.history.length})</summary>
    <ul>
      {#each reports.history as item (item.id)}
        <li>
          <button onclick={() => reports.open(item.id)}>
            <span class="kind">{item.kind}</span>
            <span class="run-name">{item.title}</span>
            <span class="run-meta tabular">
              {item.resolutions} res · {item.pages} pág. · {formatBytes(item.bytes)}
            </span>
          </button>
        </li>
      {/each}
    </ul>
  </details>
{/if}

{#if !shown.length}
  <div class="empty">
    <p><b>{narrowed ? 'Nada coincide con estos filtros.' : 'Todavía no hay nada procesado.'}</b></p>
    <p>
      {narrowed
        ? 'Pruebe ampliando el período o quitando algún filtro.'
        : 'Lo que se procese aparecerá aquí, ordenado por fecha.'}
    </p>
  </div>
{/if}

<BarraDeSeleccion
  totals={pickedTotals}
  busy={bulkBusy}
  bind:outcome={bulkOutcome}
  {nameOf}
  onremove={onremoveselected}
  onclear={onclearselection}
/>

{#each days as day (day.key)}
  <section class="day">
    <header class="day-head">
      <h3>{day.label}</h3>
      {#if day === days[0]}
        <button class="pick-all ghost" onclick={onpickall}>
          {allPicked ? 'quitar selección' : `seleccionar los ${shown.length} visibles`}
        </button>
      {/if}
      <span class="day-totals tabular">
        {day.documents} doc · {day.resolutions} res · {day.pages} pág · {formatBytes(day.bytes)}
        {#if day.review}<b class="warn">· {day.review} en revisión</b>{/if}
      </span>
    </header>

    <div class="cards">
      {#each day.entries as entry (entry.key)}
        <ProcessedCard
          {entry}
          selected={selected.has(entry.jobId)}
          onselect={onpick}
          {onchange}
        />
      {/each}
    </div>
  </section>
{/each}

{#if historyTotal > historyCount}
  <p class="muted small">
    Mostrando {historyCount} de {historyTotal} documentos del archivo. Refine la búsqueda para
    ver el resto.
  </p>
{/if}

<style>
  .summary {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem 2.25rem;
    border: 1px solid var(--hairline);
    border-radius: 14px;
    background: var(--surface-2);
    padding: 1rem 1.2rem;
    box-shadow: var(--shadow);
  }

  /* The run reports fold away: useful, but not what this screen is for. */
  .runs {
    margin: 0.75rem 0 0.25rem;
  }
  .runs summary {
    font-size: 0.78rem;
    color: var(--muted);
    cursor: pointer;
  }
  .runs ul {
    display: flex;
    flex-direction: column;
    gap: 3px;
    margin: 0.5rem 0 0;
    padding: 0;
    list-style: none;
  }
  .runs button {
    display: flex;
    width: 100%;
    align-items: baseline;
    gap: 0.6rem;
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: var(--surface-2);
    padding: 0.4rem 0.7rem;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .runs button:hover {
    border-color: var(--accent);
  }
  .kind {
    flex-shrink: 0;
    border-radius: 999px;
    background: var(--accent-soft);
    padding: 0.05rem 0.5rem;
    font-family: var(--font-mono);
    font-size: 0.62rem;
    text-transform: uppercase;
    color: var(--accent);
  }
  .run-name {
    overflow: hidden;
    flex: 1;
    font-size: 0.82rem;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .run-meta {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--muted);
  }

  .day {
    margin-top: 1.6rem;
  }
  .day-head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.45rem;
    margin-bottom: 0.9rem;
  }
  .day-head h3 {
    margin: 0;
    font-size: 0.8rem;
    font-weight: 650;
    letter-spacing: -0.005em;
    text-transform: capitalize;
  }
  /* The day heading carries its own totals: a heading that only gives the date
     makes the operator add up the cards underneath it themselves. */
  .day-totals {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--muted);
  }
  .warn {
    color: var(--warning);
  }

  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(16.5rem, 1fr));
    gap: 0.9rem;
  }

  .pick-all {
    margin-left: auto;
  }

  .muted.small {
    margin: 0 0 0.5rem;
    font-size: 0.76rem;
    color: var(--muted);
  }

  .empty {
    margin-top: 1rem;
    border: 1px dashed var(--hairline);
    border-radius: 14px;
    padding: 3rem 1.5rem;
    text-align: center;
    color: var(--muted);
  }
  .empty p {
    margin: 0 auto;
    max-width: 50ch;
    font-size: 0.85rem;
    line-height: 1.55;
  }
  .empty p + p {
    margin-top: 0.4rem;
  }

  .ghost {
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: transparent;
    padding: 0.32rem 0.7rem;
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--muted);
    cursor: pointer;
    transition:
      color 0.15s,
      border-color 0.15s;
  }
  .ghost:hover {
    border-color: var(--accent);
    color: var(--accent);
  }
</style>
