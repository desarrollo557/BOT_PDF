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
    { id: 'resoluciones', label: 'Más PDF generados' },
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
    class="input search"
    type="search"
    placeholder="Buscar por carpeta, documento, operador o número…"
    bind:value={filters.text}
  />

  <!-- Segmented controls: the options are few and mutually exclusive, so they
       are all visible rather than hidden behind a menu. -->
  <div class="segmented" role="group" aria-label="Período">
    {#each PERIODS as option (option.id)}
      <button
        class:current={filters.period === option.id}
        aria-pressed={filters.period === option.id}
        onclick={() => (filters.period = option.id)}
      >
        {option.label}
      </button>
    {/each}
  </div>

  <div class="segmented" role="group" aria-label="Estado">
    {#each STATUSES as option (option.id)}
      <button
        class:current={filters.status === option.id}
        aria-pressed={filters.status === option.id}
        onclick={() => (filters.status = option.id)}
      >
        {option.label}
      </button>
    {/each}
  </div>

  {#if people.length > 1}
    <label class="select">
      <span class="caps">Operador</span>
      <select class="input input-sm" bind:value={filters.operator}>
        <option value="todos">Todos</option>
        {#each people as person (person)}
          <option value={person}>{person}</option>
        {/each}
      </select>
    </label>
  {/if}

  <label class="select">
    <span class="caps">Orden</span>
    <select class="input input-sm" bind:value={sort}>
      {#each SORTS as option (option.id)}
        <option value={option.id}>{option.label}</option>
      {/each}
    </select>
  </label>

  {#if narrowed}
    <button class="btn btn-ghost btn-sm" onclick={reset}>Limpiar filtros</button>
  {/if}

  {#if hayEnVivo}
    {#if confirmingClear}
      <span class="confirm">
        <span>¿Vaciar la parte en vivo? El archivo queda.</span>
        <button class="btn btn-danger btn-sm" onclick={clear}>Sí, vaciar</button>
        <button class="btn btn-ghost btn-sm" onclick={() => (confirmingClear = false)}>Cancelar</button>
      </span>
    {:else}
      <button class="btn btn-ghost btn-sm" onclick={() => (confirmingClear = true)}>
        Limpiar pantalla
      </button>
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
    min-width: 0;
    flex: 1 1 100%;
    max-width: 100%;
  }
  @media (min-width: 480px) {
    .search {
      min-width: 16rem;
      flex: 1;
    }
  }

  .select {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex-wrap: wrap;
  }

  .confirm {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: var(--text-sm);
    color: var(--ink-2);
    flex-wrap: wrap;
  }

  /* En móvil, los controles segmentados se apilan si no caben */
  @media (max-width: 479px) {
    .segmented {
      width: 100%;
      justify-content: flex-start;
    }
    .select {
      width: 100%;
    }
    .filters > .btn {
      width: 100%;
    }
  }
</style>
