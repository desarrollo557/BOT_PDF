<script lang="ts">
  /**
   * Borrar varios documentos de una vez, y decir qué pasó con cada uno.
   *
   * Borrar de a uno está bien para corregir un error; no lo está para vaciar
   * una caja mal procesada, que son decenas de documentos y decenas de
   * confirmaciones.
   *
   * Las reglas de qué está seleccionado viven en `archive.svelte.ts` y se
   * prueban sin dibujar nada; aquí sólo quedan la confirmación y el parte de lo
   * que se borró.
   */
  interface Totales {
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
    totals,
    busy = false,
    outcome = $bindable(),
    nameOf,
    onremove,
    onclear
  }: {
    totals: Totales;
    busy?: boolean;
    outcome: Resultado | null;
    /** El nombre del documento, para poder nombrar al que no se pudo borrar. */
    nameOf: (jobId: string) => string;
    onremove: () => void;
    onclear: () => void;
  } = $props();

  let confirming = $state(false);

  // Si la selección cambia de tamaño, la confirmación que había deja de
  // referirse a lo que el operador está viendo.
  $effect(() => {
    totals.documents;
    confirming = false;
  });
</script>

{#if totals.documents}
  <section class="bulk" aria-live="polite">
    <span class="count">
      <b class="tabular">{totals.documents}</b>
      {totals.documents === 1 ? 'documento seleccionado' : 'documentos seleccionados'}
      <span class="muted tabular">· {totals.resolutions} PDF · {totals.pages} pág.</span>
    </span>

    {#if confirming}
      <span class="confirm">
        <span>
          Se eliminarán <b>{totals.documents}</b>
          {totals.documents === 1 ? 'documento' : 'documentos'} con sus PDF y sus filas del
          inventario. No se puede deshacer.
        </span>
        <button class="btn btn-danger btn-sm" onclick={onremove} disabled={busy}>
          {busy ? 'Eliminando…' : 'Sí, eliminar'}
        </button>
        <button class="btn btn-ghost btn-sm" onclick={() => (confirming = false)} disabled={busy}>
          Cancelar
        </button>
      </span>
    {:else}
      <button class="btn btn-danger btn-sm" onclick={() => (confirming = true)}>
        Eliminar seleccionados
      </button>
      <button class="btn btn-ghost btn-sm" onclick={onclear}>Quitar selección</button>
    {/if}
  </section>
{/if}

{#if outcome}
  <section class="outcome" aria-live="polite">
    <p>
      Se eliminaron <b>{outcome.deleted}</b>
      {outcome.deleted === 1 ? 'documento' : 'documentos'}
      {#if outcome.rows}
        y <b>{outcome.rows}</b> filas del inventario{/if}.
    </p>
    {#if outcome.failed.length}
      <!-- Los que no se pudieron borrar se nombran uno a uno con su motivo:
           un lote que dice "hecho" habiendo fallado la mitad es peor que uno
           que falla entero. -->
      <ul class="failed">
        {#each outcome.failed as item (item.job_id)}
          <li>{nameOf(item.job_id)} — {item.reason}</li>
        {/each}
      </ul>
    {/if}
    <button class="btn btn-sm" onclick={() => (outcome = null)}>Entendido</button>
  </section>
{/if}

<style>
  .bulk {
    position: sticky;
    /* Debajo de la barra fija de arriba, no escondida tras ella. */
    top: 4.5rem;
    z-index: 3;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.9rem;
    padding: 0.6rem 0.85rem;
    border: 1px solid var(--hairline);
    border-radius: var(--radius-md);
    background: var(--surface-2);
    box-shadow: var(--shadow);
  }

  .bulk .count {
    margin-right: auto;
  }

  .bulk .muted {
    color: var(--muted);
  }

  .outcome {
    margin-bottom: 0.9rem;
    padding: 0.6rem 0.85rem;
    border-left: 3px solid var(--accent);
    border-radius: var(--radius-sm);
    background: var(--plane);
  }

  .outcome .failed {
    margin: 0.4rem 0 0.6rem;
    padding-left: 1.1rem;
    color: var(--warning-ink);
  }

  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem;
    font-size: var(--text-sm);
    color: var(--ink-2);
  }
</style>
