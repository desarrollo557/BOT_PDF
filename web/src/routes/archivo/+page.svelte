<script lang="ts">
  import {
    deleteOutput,
    downloadUrl,
    fetchInventory,
    fetchProcessedDocuments,
    inventoryUrl,
    renameOutput
  } from '$lib/api';
  import {
    apply,
    byDay,
    EMPTY_FILTERS,
    merge,
    operators,
    type Filters,
    type Period,
    type Sort,
    type Status
  } from '$lib/archive.svelte';
  import ProcessedCard from '$lib/components/ProcessedCard.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import { formatBytes } from '$lib/format';
  import { jobStore } from '$lib/jobs.svelte';
  import { reports } from '$lib/report.svelte';
  import type { InventoryPage, ProcessedDocument } from '$lib/types';

  /**
   * One archive, two grains.
   *
   * Documents and resolutions were two screens showing the same work at two
   * levels, and an operator looking for "la 00086" had to guess which one held
   * it. They are the same question, so the grain is a control, not a
   * destination.
   */
  type Grain = 'documentos' | 'resoluciones';
  let grain = $state<Grain>('documentos');

  let filters = $state<Filters>({ ...EMPTY_FILTERS });
  let sort = $state<Sort>('reciente');

  /** The text actually applied, debounced so typing does not query per key. */
  let applied = $state('');
  let timer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const next = filters.text;
    clearTimeout(timer);
    timer = setTimeout(() => (applied = next.trim()), 220);
    return () => clearTimeout(timer);
  });

  let history = $state<ProcessedDocument[]>([]);
  let resolutions = $state<InventoryPage | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  $effect(() => {
    void load(applied, grain);
  });
  // Reload when the live side finishes something, so it lands here by itself.
  $effect(() => {
    jobStore.finished.length;
    void load(applied, grain);
  });

  async function load(needle: string, which: Grain) {
    loading = true;
    error = null;
    try {
      if (which === 'documentos') history = (await fetchProcessedDocuments(needle)).documents;
      else resolutions = await fetchInventory(needle, 400);
    } catch (problem) {
      error = (problem as Error).message;
    } finally {
      loading = false;
    }
  }

  // -- documents ---------------------------------------------------------------

  const everything = $derived(merge(jobStore.finished, history));
  const shown = $derived(apply(everything, { ...filters, text: applied }));
  const days = $derived(byDay(shown, sort));
  const people = $derived(operators(everything));

  const totals = $derived({
    documents: shown.length,
    resolutions: shown.reduce((sum, entry) => sum + entry.resolutions, 0),
    pages: shown.reduce((sum, entry) => sum + entry.pages, 0),
    bytes: shown.reduce((sum, entry) => sum + entry.bytes, 0),
    review: shown.reduce((sum, entry) => sum + entry.review, 0)
  });

  const narrowed = $derived(
    applied !== '' ||
      filters.period !== 'todo' ||
      filters.status !== 'todos' ||
      filters.operator !== 'todos'
  );

  const PERIODS: { id: Period; label: string }[] = [
    { id: 'hoy', label: 'Hoy' },
    { id: 'semana', label: '7 días' },
    { id: 'mes', label: '30 días' },
    { id: 'todo', label: 'Todo' }
  ];

  const STATUSES: { id: Status; label: string }[] = [
    { id: 'todos', label: 'Todos' },
    { id: 'revision', label: 'Con revisión' },
    { id: 'limpios', label: 'Sin pendientes' },
    { id: 'fallidos', label: 'Fallidos' }
  ];

  const SORTS: { id: Sort; label: string }[] = [
    { id: 'reciente', label: 'Más reciente' },
    { id: 'antiguo', label: 'Más antiguo' },
    { id: 'resoluciones', label: 'Más resoluciones' },
    { id: 'paginas', label: 'Más páginas' },
    { id: 'nombre', label: 'Nombre' }
  ];

  function reset() {
    filters = { ...EMPTY_FILTERS };
    sort = 'reciente';
  }

  // -- resolutions, inline correction ------------------------------------------

  const rows = $derived(resolutions?.rows ?? []);
  const summary = $derived(resolutions?.summary);

  let editing = $state<string | null>(null);
  let draftCode = $state('');
  let draftTitle = $state('');
  let rowBusy = $state(false);
  let rowError = $state<string | null>(null);

  const keyOf = (row: { job_id: string; file_name: string }) => `${row.job_id}/${row.file_name}`;

  function edit(row: { job_id: string; file_name: string; code: string; title: string | null }) {
    editing = keyOf(row);
    draftCode = row.code;
    draftTitle = row.title ?? '';
    rowError = null;
  }

  async function saveRow(row: { job_id: string; file_name: string }) {
    rowBusy = true;
    rowError = null;
    try {
      await renameOutput(row.job_id, row.file_name, {
        code: draftCode.trim(),
        title: draftTitle.trim() || null
      });
      editing = null;
      await load(applied, grain);
    } catch (problem) {
      rowError = (problem as Error).message;
    } finally {
      rowBusy = false;
    }
  }

  async function removeRow(row: { job_id: string; file_name: string }) {
    rowBusy = true;
    rowError = null;
    try {
      await deleteOutput(row.job_id, row.file_name);
      editing = null;
      await load(applied, grain);
    } catch (problem) {
      rowError = (problem as Error).message;
    } finally {
      rowBusy = false;
    }
  }

  let confirmingClear = $state(false);
  async function clear() {
    confirmingClear = false;
    try {
      await jobStore.clear();
      await load(applied, grain);
    } catch (problem) {
      error = `No se pudo limpiar: ${(problem as Error).message}`;
    }
  }
</script>

<header class="head">
  <div>
    <h2>Archivo</h2>
    <p>
      Todo lo que salió del separador. Búsquelo por documento de origen o por número de
      resolución — es el mismo archivo visto con dos lupas distintas.
    </p>
  </div>

  <div class="grain" role="tablist" aria-label="Nivel de detalle">
    {#each [{ id: 'documentos', label: 'Por documento' }, { id: 'resoluciones', label: 'Por resolución' }] as tab (tab.id)}
      <button
        role="tab"
        aria-selected={grain === tab.id}
        class:current={grain === tab.id}
        onclick={() => (grain = tab.id as Grain)}
      >
        {tab.label}
      </button>
    {/each}
  </div>
</header>

{#if error}<p class="error">{error}</p>{/if}

{#if grain === 'documentos'}
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

  <section class="filters" aria-label="Filtros">
    <input
      class="search"
      type="search"
      placeholder="Buscar por nombre de archivo…"
      bind:value={filters.text}
    />

    <div class="group" role="group" aria-label="Período">
      {#each PERIODS as option (option.id)}
        <button
          class:current={filters.period === option.id}
          onclick={() => (filters.period = option.id)}
        >
          {option.label}
        </button>
      {/each}
    </div>

    <div class="group" role="group" aria-label="Estado">
      {#each STATUSES as option (option.id)}
        <button
          class:current={filters.status === option.id}
          onclick={() => (filters.status = option.id)}
        >
          {option.label}
        </button>
      {/each}
    </div>

    {#if people.length > 1}
      <label class="select">
        <span>Operador</span>
        <select bind:value={filters.operator}>
          <option value="todos">Todos</option>
          {#each people as person (person)}
            <option value={person}>{person}</option>
          {/each}
        </select>
      </label>
    {/if}

    <label class="select">
      <span>Orden</span>
      <select bind:value={sort}>
        {#each SORTS as option (option.id)}
          <option value={option.id}>{option.label}</option>
        {/each}
      </select>
    </label>

    {#if narrowed}
      <button class="ghost" onclick={reset}>limpiar filtros</button>
    {/if}

    {#if jobStore.finished.length}
      {#if confirmingClear}
        <span class="confirm">
          <span>¿Vaciar la parte en vivo? El archivo queda.</span>
          <button class="danger" onclick={clear}>Sí</button>
          <button class="ghost" onclick={() => (confirmingClear = false)}>No</button>
        </span>
      {:else}
        <button class="ghost" onclick={() => (confirmingClear = true)}>limpiar pantalla</button>
      {/if}
    {/if}
  </section>

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

  {#each days as day (day.key)}
    <section class="day">
      <header class="day-head">
        <h3>{day.label}</h3>
        <span class="day-totals tabular">
          {day.documents} doc · {day.resolutions} res · {day.pages} pág · {formatBytes(day.bytes)}
          {#if day.review}<b class="warn">· {day.review} en revisión</b>{/if}
        </span>
      </header>

      <div class="cards">
        {#each day.entries as entry (entry.key)}
          <ProcessedCard {entry} onchange={() => load(applied, grain)} />
        {/each}
      </div>
    </section>
  {/each}
{:else}
  {#if summary}
    <section class="summary">
      <StatTile label="Resoluciones" value={summary.resolutions} note="archivos generados" />
      <StatTile label="Números distintos" value={summary.codes} />
      <StatTile label="Documentos de origen" value={summary.documents} />
      <StatTile label="Páginas" value={summary.pages} />
    </section>
  {/if}

  <section class="filters">
    <input
      class="search"
      type="search"
      placeholder="Buscar por número, título, documento u operador…"
      bind:value={filters.text}
    />
    <a class="ghost" href={inventoryUrl(applied)} download>exportar a Excel</a>
  </section>

  {#if loading && !rows.length}
    <p class="muted">Cargando…</p>
  {:else if !rows.length}
    <p class="muted">
      {applied ? `Nada coincide con «${applied}».` : 'Todavía no se generó ninguna resolución.'}
    </p>
  {:else}
    {#if resolutions && resolutions.total > rows.length}
      <p class="muted small">
        Mostrando {rows.length} de {resolutions.total}. Refine la búsqueda para ver el resto.
      </p>
    {/if}

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Resolución</th>
            <th>Título</th>
            <th>Documento de origen</th>
            <th>Operador</th>
            <th>Páginas</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {#each rows as row (keyOf(row))}
            <tr>
              {#if editing === keyOf(row)}
                <td colspan="6" class="editor">
                  <div class="fields">
                    <label>
                      <span>Número</span>
                      <input class="code-input" bind:value={draftCode} spellcheck="false" />
                    </label>
                    <label class="grow">
                      <span>Título</span>
                      <input bind:value={draftTitle} placeholder="sin título" />
                    </label>
                    <button
                      class="primary"
                      onclick={() => saveRow(row)}
                      disabled={rowBusy || !draftCode.trim()}
                    >
                      {rowBusy ? 'guardando…' : 'guardar'}
                    </button>
                    <button class="danger" onclick={() => removeRow(row)} disabled={rowBusy}>
                      eliminar
                    </button>
                    <button class="ghost" onclick={() => (editing = null)} disabled={rowBusy}>
                      cancelar
                    </button>
                  </div>
                  {#if rowError}<p class="error inline">{rowError}</p>{/if}
                </td>
              {:else}
                <td class="mono">{row.code}</td>
                <td class="dim">{row.title ?? '—'}</td>
                <td class="dim">{row.source_document}</td>
                <td class="dim">{row.operator ?? '—'}</td>
                <td class="mono">{row.pages} <span class="muted">({row.page_count})</span></td>
                <td class="tools">
                  <a href={downloadUrl(row.job_id, row.file_name)} download>PDF</a>
                  <button onclick={() => edit(row)}>editar</button>
                </td>
              {/if}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
{/if}

<style>
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1.25rem;
  }
  .head h2 {
    margin: 0;
    font-size: 1.25rem;
    font-weight: 650;
    letter-spacing: -0.015em;
  }
  .head p {
    margin: 0.3rem 0 0;
    max-width: 64ch;
    font-size: 0.85rem;
    line-height: 1.5;
    color: var(--ink-2);
  }

  .grain {
    display: flex;
    gap: 2px;
    border: 1px solid var(--hairline);
    border-radius: 9px;
    background: var(--plane);
    padding: 3px;
  }
  .grain button {
    border: 0;
    border-radius: 6px;
    background: transparent;
    padding: 0.3rem 0.8rem;
    font: inherit;
    font-size: 0.82rem;
    color: var(--muted);
    cursor: pointer;
    transition:
      background 0.15s,
      color 0.15s;
  }
  .grain button.current {
    background: var(--surface-2);
    box-shadow: var(--shadow);
    color: var(--ink);
  }

  .error {
    margin: 0 0 1rem;
    border-left: 2px solid var(--critical);
    padding-left: 0.65rem;
    font-size: 0.85rem;
    color: var(--critical);
  }
  .error.inline {
    margin: 0.5rem 0 0;
  }

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

  .filters {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin: 1.1rem 0 0.5rem;
  }
  .search {
    min-width: 16rem;
    flex: 1;
    border: 1px solid var(--hairline);
    border-radius: 9px;
    background: var(--surface-2);
    padding: 0.45rem 0.75rem;
    font: inherit;
    font-size: 0.85rem;
    color: inherit;
    outline: none;
  }
  .search:focus {
    border-color: var(--accent);
  }

  /* Segmented controls: the options are few and mutually exclusive, so they are
     all visible rather than hidden behind a menu. */
  .group {
    display: flex;
    gap: 2px;
    border: 1px solid var(--hairline);
    border-radius: 9px;
    background: var(--plane);
    padding: 2px;
  }
  .group button {
    border: 0;
    border-radius: 6px;
    background: transparent;
    padding: 0.25rem 0.6rem;
    font: inherit;
    font-size: 0.78rem;
    color: var(--muted);
    cursor: pointer;
    transition:
      background 0.15s,
      color 0.15s;
  }
  .group button.current {
    background: var(--surface-2);
    box-shadow: var(--shadow);
    color: var(--ink);
  }

  .select {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.72rem;
    color: var(--muted);
  }
  .select select {
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: var(--surface-2);
    padding: 0.3rem 0.5rem;
    font: inherit;
    font-size: 0.8rem;
    color: var(--ink);
  }

  .confirm {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.8rem;
    color: var(--ink-2);
  }

  .ghost,
  .primary,
  .danger {
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: transparent;
    padding: 0.32rem 0.7rem;
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--muted);
    text-decoration: none;
    cursor: pointer;
    transition:
      color 0.15s,
      border-color 0.15s,
      background 0.15s;
  }
  .ghost:hover {
    border-color: var(--accent);
    color: var(--accent);
  }
  .primary {
    border-color: var(--accent);
    color: var(--accent);
  }
  .danger {
    border-color: var(--critical);
    color: var(--critical);
  }
  .danger:hover {
    background: var(--critical);
    color: #fff;
  }
  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
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

  .table-wrap {
    overflow-x: auto;
    border: 1px solid var(--hairline);
    border-radius: 14px;
    background: var(--surface-2);
    box-shadow: var(--shadow);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
  }
  thead th {
    padding: 0.7rem 0.75rem;
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
    padding: 0.55rem 0.75rem;
  }
  .mono {
    font-family: var(--font-mono);
    font-size: 0.76rem;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .dim {
    color: var(--ink-2);
  }
  .muted {
    color: var(--muted);
  }
  .muted.small {
    margin: 0 0 0.5rem;
    font-size: 0.76rem;
  }

  .tools {
    display: flex;
    justify-content: flex-end;
    gap: 0.8rem;
    white-space: nowrap;
  }
  .tools a {
    color: var(--accent);
    text-decoration: none;
  }
  .tools a:hover {
    text-decoration: underline;
  }
  .tools button {
    border: 0;
    background: none;
    padding: 0;
    font: inherit;
    color: var(--muted);
    cursor: pointer;
  }
  .tools button:hover {
    color: var(--ink);
  }

  .editor {
    background: var(--plane);
  }
  .fields {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 0.6rem;
  }
  .fields label {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }
  .fields .grow {
    min-width: 14rem;
    flex: 1;
  }
  .fields span {
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .fields input {
    border: 1px solid var(--hairline);
    border-radius: 7px;
    background: var(--surface-2);
    padding: 0.35rem 0.55rem;
    font: inherit;
    font-size: 0.85rem;
    color: inherit;
    outline: none;
  }
  .fields input:focus {
    border-color: var(--accent);
  }
  .code-input {
    width: 9rem;
    font-family: var(--font-mono);
    font-size: 0.8rem;
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
</style>
