<script lang="ts">
  import { page } from '$app/state';
  import { deleteDocuments, fetchInventory, fetchProcessedDocuments } from '$lib/api';
  import {
    apply,
    byDay,
    EMPTY_FILTERS,
    merge,
    operators,
    selectionTotals,
    toggle,
    toggleAll,
    toggleMany,
    visibleSelection,
    type Filters,
    type Sort
  } from '$lib/archive.svelte';
  import PestanaDocumentos from '$lib/components/archivo/PestanaDocumentos.svelte';
  import PestanaResoluciones from '$lib/components/archivo/PestanaResoluciones.svelte';
  import EncabezadoDePagina from '$lib/components/EncabezadoDePagina.svelte';
  import { jobStore } from '$lib/jobs.svelte';
  import type { InventoryPage, ProcessedDocument } from '$lib/types';
  import type { Snapshot } from './$types';

  /**
   * One archive, two grains.
   *
   * Documents and resolutions were two screens showing the same work at two
   * levels, and an operator looking for "la 00086" had to guess which one held
   * it. They are the same question, so the grain is a control, not a
   * destination.
   *
   * Cada lupa vive en su propio componente; aquí queda lo que las dos
   * comparten: qué se busca, qué se ha traído del servicio y qué está marcado.
   */
  type Grain = 'documentos' | 'resoluciones';
  let grain = $state<Grain>('documentos');

  // `?q=` abre el archivo ya buscando: es como «Volver» lleva de un documento
  // a la carpeta de la que colgaba.
  let filters = $state<Filters>({ ...EMPTY_FILTERS, text: page.url.searchParams.get('q') ?? '' });
  let sort = $state<Sort>('reciente');

  $effect(() => {
    const pedido = page.url.searchParams.get('q');
    if (pedido !== null) filters.text = pedido;
  });

  /**
   * Lo que se estaba mirando, guardado al salir hacia un documento: volver por
   * el historial devuelve la misma pestaña, la misma búsqueda y el mismo orden
   * en vez de un archivo en blanco.
   */
  export const snapshot: Snapshot<{ grain: Grain; filters: Filters; sort: Sort }> = {
    capture: () => ({ grain, filters: $state.snapshot(filters), sort }),
    restore: (guardado) => {
      grain = guardado.grain;
      filters = guardado.filters;
      sort = guardado.sort;
    }
  };

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
  /** Cuántos documentos responden en el archivo, aunque no quepan todos en la página. */
  let historyTotal = $state(0);
  let resolutions = $state<InventoryPage | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  // Un solo efecto para las tres cosas que piden recargar -- lo que se busca,
  // la pestaña y lo que termina en la otra pantalla -- porque dos efectos
  // separados disparaban dos peticiones por cada cambio.
  $effect(() => {
    jobStore.finished.length;
    void load(applied, grain);
  });

  /**
   * Número de la última petición lanzada. Escribir «fac» y luego «factura»
   * son dos peticiones en vuelo, y la primera puede llegar después: sin esto
   * la pantalla se quedaba con el resultado de lo que ya no se buscaba.
   */
  let turno = 0;

  async function load(needle: string, which: Grain) {
    const mio = ++turno;
    loading = true;
    try {
      if (which === 'documentos') {
        const page = await fetchProcessedDocuments(needle);
        if (mio !== turno) return;
        history = page.documents;
        historyTotal = page.total;
      } else {
        const page = await fetchInventory(needle, 400);
        if (mio !== turno) return;
        resolutions = page;
      }
      // Se borra al primer resultado bueno y no al empezar a cargar: borrarlo
      // antes hacía parpadear el aviso en cada tecla mientras el fallo seguía.
      error = null;
    } catch (problem) {
      if (mio !== turno) return;
      error = (problem as Error).message;
    } finally {
      if (mio === turno) loading = false;
    }
  }

  const recargar = () => void load(applied, grain);

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
    review: shown.reduce((sum, entry) => sum + entry.review, 0),
    carpetas: new Set(shown.map((entry) => entry.origen?.id).filter(Boolean)).size
  });

  const narrowed = $derived(
    applied !== '' ||
      filters.period !== 'todo' ||
      filters.status !== 'todos' ||
      filters.operator !== 'todos'
  );

  /* -------------------------------------------------------------------------
     Selección múltiple
     -------------------------------------------------------------------------
     Borrar de a uno está bien para corregir un error; no lo está para vaciar
     una caja mal procesada, que son decenas de documentos y decenas de
     confirmaciones. Las reglas viven en `archive.svelte.ts` -- se prueban sin
     dibujar nada -- y el estado vive aquí, porque quien llama al servicio y
     recarga la lista es esta página.
  */
  let selected = $state<Set<string>>(new Set());
  let bulkBusy = $state(false);
  let bulkOutcome = $state<{
    deleted: number;
    rows: number;
    failed: { job_id: string; reason: string }[];
  } | null>(null);

  /* Lo marcado que además sigue a la vista. Si el operador marca veinte, cambia
     el filtro y pulsa eliminar, sólo se borra lo que está viendo: una selección
     que sobrevive a su propia lista es una forma de borrar a ciegas. */
  const picked = $derived(visibleSelection(selected, shown));
  const pickedTotals = $derived(selectionTotals(selected, shown));
  const allPicked = $derived(shown.length > 0 && picked.length === shown.length);

  function pick(jobId: string) {
    selected = toggle(selected, jobId);
    bulkOutcome = null;
  }

  function pickMany(jobIds: string[]) {
    selected = toggleMany(selected, jobIds);
    bulkOutcome = null;
  }

  function pickAll() {
    selected = toggleAll(selected, shown);
    bulkOutcome = null;
  }

  /* El nombre del documento, para poder nombrar al que no se pudo borrar.
     Un identificador de treinta y dos caracteres no le dice nada a nadie. */
  function nameOf(jobId: string): string {
    return everything.find((entry) => entry.jobId === jobId)?.name ?? jobId;
  }

  function clearSelection() {
    selected = new Set();
    bulkOutcome = null;
  }

  async function removeSelected() {
    if (!picked.length) return;
    bulkBusy = true;
    bulkOutcome = null;
    try {
      const result = await deleteDocuments(picked);
      // Lo que se borró deja de estar marcado; lo que falló sigue marcado, para
      // que el operador vea exactamente qué queda por resolver.
      const survivors = new Set(selected);
      for (const item of result.deleted) {
        survivors.delete(item.job_id);
        // Y deja de estar pendiente de revisión: ya no existe.
        jobStore.forget(item.job_id);
      }
      selected = survivors;
      bulkOutcome = {
        deleted: result.deleted.length,
        rows: result.rows,
        failed: result.failed
      };
      await load(applied, grain);
    } catch (problem) {
      error = `No se pudieron eliminar: ${(problem as Error).message}`;
    } finally {
      bulkBusy = false;
    }
  }

  async function clearScreen() {
    try {
      await jobStore.clear();
      await load(applied, grain);
    } catch (problem) {
      error = `No se pudo limpiar: ${(problem as Error).message}`;
    }
  }
</script>

<EncabezadoDePagina
  titulo="Archivo"
  descripcion="Todo lo que se ha procesado. Lo que vino de una carpeta local o de un lote aparece reunido bajo el nombre de esa carpeta. Busque por carpeta, por PDF de origen, por operador o por número del documento."
>
  {#snippet acciones()}
    <div class="segmented" role="tablist" aria-label="Nivel de detalle">
      {#each [{ id: 'documentos', label: 'Por documento' }, { id: 'resoluciones', label: 'Por PDF generado' }] as tab (tab.id)}
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
  {/snippet}
</EncabezadoDePagina>

{#if error}<p class="inline-error page-error">{error}</p>{/if}

{#if grain === 'documentos'}
  <PestanaDocumentos
    bind:filters
    bind:sort
    bind:bulkOutcome
    {everything}
    {shown}
    {days}
    {totals}
    {narrowed}
    {people}
    hayEnVivo={jobStore.finished.length > 0}
    {selected}
    {allPicked}
    {pickedTotals}
    {bulkBusy}
    historyCount={history.length}
    {historyTotal}
    {nameOf}
    onpick={pick}
    onpickmany={pickMany}
    onpickall={pickAll}
    onclearselection={clearSelection}
    onremoveselected={removeSelected}
    onclearscreen={clearScreen}
    onchange={recargar}
  />
{:else}
  <PestanaResoluciones bind:filters {resolutions} {loading} {applied} onreload={recargar} />
{/if}

<style>
  /* El aviso de la página va encima de las pestañas, separado de lo que sigue. */
  .page-error {
    margin: 0 0 1rem;
  }
</style>
