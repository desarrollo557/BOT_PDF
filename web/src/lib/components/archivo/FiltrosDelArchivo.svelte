<script lang="ts">
  /**
   * Con qué se acota el archivo: el buscador y los cuatro ejes.
   *
   * Los ejes son pocos y excluyentes entre sí, así que están todos a la vista
   * en vez de escondidos tras un menú. El buscador se maneja fuera -- lo que se
   * escribe se aplica con retardo y viaja al servicio -- y aquí sólo se enlaza.
   */
  import { EMPTY_FILTERS, type Filters, type Period, type Sort, type Status } from '$lib/archive.svelte';

  let {
    filters = $bindable(),
    sort = $bindable(),
    people,
    narrowed,
    hayEnVivo = false,
    onclear
  }: {
    filters: Filters;
    sort: Sort;
    /** Quiénes procesaron algo de lo que hay. Con uno solo no hay qué elegir. */
    people: string[];
    /** Si algún filtro está puesto, para ofrecer quitarlos. */
    narrowed: boolean;
    /** Si queda algo en la parte en vivo que se pueda vaciar. */
    hayEnVivo?: boolean;
    onclear: () => void;
  } = $props();

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

  let confirmingClear = $state(false);

  function clear() {
    confirmingClear = false;
    onclear();
  }
</script>

<section class="filters" aria-label="Filtros">
  <input
    class="search"
    type="search"
    placeholder="Buscar por carpeta, documento, operador o número…"
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

  {#if hayEnVivo}
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

<style>
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
  .danger {
    border-color: var(--critical);
    color: var(--critical);
  }
  .danger:hover {
    background: var(--critical);
    color: #fff;
  }
</style>
