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
  import CarpetaCard from './CarpetaCard.svelte';
  import FiltrosDelArchivo from './FiltrosDelArchivo.svelte';

  interface Totales {
    documents: number;
    resolutions: number;
    pages: number;
    bytes: number;
    review: number;
    /** Cuántas carpetas locales o lotes hay entre lo que se ve. */
    carpetas: number;
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
    onpickmany,
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
    /** Marcar o desmarcar todos los PDF de una carpeta de una vez. */
    onpickmany: (jobIds: string[]) => void;
    onpickall: () => void;
    onclearselection: () => void;
    onremoveselected: () => void;
    onclearscreen: () => void;
    onchange: () => void;
  } = $props();
</script>

<!-- Totals for what is actually on screen, so narrowing the filters answers
     "how much is this" without anybody adding up cards. -->
<section class="panel summary">
  <StatTile
    label={narrowed ? 'PDF filtrados' : 'PDF procesados'}
    value={totals.documents}
    note={narrowed ? `de ${everything.length} en total` : 'de origen'}
  />
  <StatTile
    label="Carpetas y lotes"
    value={totals.carpetas}
    note={totals.carpetas ? 'enteros' : 'ninguno'}
  />
  <StatTile label="Unidades" value={totals.resolutions} note="generadas" />
  <StatTile label="Páginas" value={totals.pages} />
  <StatTile label="Peso neto" value={formatBytes(totals.bytes)} note="de origen" />
  <StatTile
    label="En revisión"
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
          <button class="panel panel-sm panel-interactive" onclick={() => reports.open(item.id)}>
            <span class="pill kind">{item.kind}</span>
            <span class="run-name">{item.title}</span>
            <span class="run-meta tabular">
              {item.resolutions} PDF · {item.pages} pág. · {formatBytes(item.bytes)}
            </span>
          </button>
        </li>
      {/each}
    </ul>
  </details>
{/if}

{#if !shown.length}
  <div class="empty-state empty">
    <strong>{narrowed ? 'Nada coincide con estos filtros.' : 'Todavía no hay nada procesado.'}</strong>
    {narrowed
      ? 'Pruebe ampliando el período o quitando algún filtro.'
      : 'Lo que se procese aparecerá aquí, ordenado por fecha.'}
  </div>
{/if}

{#if shown.length}
  <div class="list-bar">
    <span class="tabular">
      {shown.length}
      PDF{#if totals.carpetas}, {totals.carpetas}
        {totals.carpetas === 1 ? 'carpeta o lote' : 'carpetas o lotes'}{/if}
    </span>
    <button class="btn btn-ghost btn-sm" onclick={onpickall}>
      {allPicked ? 'Quitar selección' : `Seleccionar los ${shown.length} visibles`}
    </button>
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
      <span class="day-totals tabular">
        {day.documents} PDF · {day.resolutions} unidades · {day.pages} pág. · {formatBytes(day.bytes)}
        {#if day.review}<b class="warn">· {day.review} en revisión</b>{/if}
      </span>
    </header>

    <div class="cards" class:single-carpeta={day.items.length === 1 && day.items[0]?.kind === 'grupo'}>
      {#each day.items as item (item.key)}
        {#if item.kind === 'grupo'}
          <CarpetaCard grupo={item.grupo} {selected} onselectmany={onpickmany} {onchange} />
        {:else}
          <ProcessedCard
            entry={item.entry}
            selected={selected.has(item.entry.jobId)}
            onselect={onpick}
            {onchange}
          />
        {/if}
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
  /* Las seis cifras en una fila mientras quepan a 5.75rem cada una: con huecos
     fijos de 2.25rem partían en dos renglones al lado de la consola. */
  .summary {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(5.75rem, 1fr));
    gap: 0.75rem;
  }

  /* The run reports fold away: useful, but not what this screen is for. */
  .runs {
    margin: 0.75rem 0 0.25rem;
  }
  .runs summary {
    font-size: var(--text-sm);
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
  /* Cada informe es una fila entera que se pulsa: la tarjeta-control común
     (`.panel-interactive`), con el relleno corto de una lista. */
  .runs button {
    display: flex;
    width: 100%;
    align-items: baseline;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
  }
  /* El tipo de corrida es un rótulo, no un código: va en versalitas sans. */
  .kind {
    flex-shrink: 0;
    font-size: var(--text-2xs);
    letter-spacing: var(--tracking-caps);
    text-transform: uppercase;
  }
  .run-name {
    overflow: hidden;
    flex: 1;
    font-size: var(--text-sm);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .run-meta {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
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
    font-size: var(--text-sm);
    font-weight: 650;
    letter-spacing: -0.005em;
    text-transform: capitalize;
  }
  /* The day heading carries its own totals: a heading that only gives the date
     makes the operator add up the cards underneath it themselves. */
  .day-totals {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .warn {
    color: var(--warning-ink);
  }

  .cards {
    display: grid;
    align-items: start;
    grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
    gap: 0.75rem;
  }

  /* Una sola CarpetaCard en su día: que ocupe el ancho completo
     para que no quede una tarjeta flotando en una columna. */
  .cards.single-carpeta {
    grid-template-columns: 1fr;
  }

  .list-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    margin-top: 0.75rem;
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .muted.small {
    margin: 0 0 0.5rem;
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .empty {
    margin-top: 1rem;
    line-height: 1.55;
  }
</style>
