<script lang="ts">
  /**
   * El archivo visto unidad por unidad: cada PDF que se produjo, con su número,
   * su tipo documental y las páginas de las que salió.
   *
   * Es la lupa fina de la pantalla de Archivo, y la única donde se corrige: el
   * OCR se equivoca de dígito con la frecuencia suficiente como para que
   * arreglarlo no pueda costar volver a procesar el documento entero.
   */
  import { deleteOutput, downloadUrl, inventoryUrl, renameOutput } from '$lib/api';
  import type { Filters } from '$lib/archive.svelte';
  import { confirmar } from '$lib/confirmar.svelte';
  import Icono from '$lib/components/Icono.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import type { InventoryPage } from '$lib/types';

  let {
    filters = $bindable(),
    resolutions,
    loading = false,
    applied,
    onreload
  }: {
    filters: Filters;
    resolutions: InventoryPage | null;
    loading?: boolean;
    /** Lo que de verdad se está buscando, ya aplicado. */
    applied: string;
    onreload: () => void;
  } = $props();

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

  /**
   * Qué le falta a la corrección: los dos campos, siempre y para todos.
   *
   * Una corrección se manda entera o no se manda. Un título en blanco no es una
   * decisión, es un campo que se quedó sin llenar, y se queda así para siempre
   * porque nadie vuelve sobre una fila del inventario que ya pasó. Es la misma
   * regla del resto de los formularios del programa.
   */
  const faltaElCodigo = $derived(!draftCode.trim());
  const faltaElTitulo = $derived(!draftTitle.trim());
  const puedeGuardarLaFila = $derived(!rowBusy && !faltaElCodigo && !faltaElTitulo);

  async function saveRow(row: { job_id: string; file_name: string }) {
    // La misma guarda que apaga el botón, otra vez aquí: se puede pulsar con el
    // teclado antes de que la pantalla repinte, y la regla tiene que estar
    // donde se ejecuta la acción y no sólo donde se dibuja.
    if (!puedeGuardarLaFila) return;
    rowBusy = true;
    rowError = null;
    try {
      await renameOutput(row.job_id, row.file_name, {
        code: draftCode.trim(),
        title: draftTitle.trim()
      });
      editing = null;
      onreload();
    } catch (problem) {
      rowError = (problem as Error).message;
    } finally {
      rowBusy = false;
    }
  }

  async function removeRow(row: { job_id: string; file_name: string }) {
    const seguro = await confirmar({
      titulo: '¿Eliminar este documento?',
      mensaje: `Se borra «${row.file_name}» y su fila del inventario. No se puede deshacer.`,
      aceptar: 'Eliminar',
      peligro: true
    });
    if (!seguro) return;
    rowBusy = true;
    rowError = null;
    try {
      await deleteOutput(row.job_id, row.file_name);
      editing = null;
      onreload();
    } catch (problem) {
      rowError = (problem as Error).message;
    } finally {
      rowBusy = false;
    }
  }
</script>

{#if summary}
  <section class="panel summary">
    <StatTile label="PDF generados" value={summary.resolutions} />
    <StatTile label="Números distintos" value={summary.codes} />
    <StatTile label="Documentos de origen" value={summary.documents} />
    <StatTile label="Páginas" value={summary.pages} />
  </section>
{/if}

<section class="filters">
  <input
    class="input search"
    type="search"
    placeholder="Buscar por número, tipo, fecha, NIC, documento u operador…"
    bind:value={filters.text}
  />
  <!-- De cajas de correspondencia, el servicio entrega el Índice Electrónico
       del cliente, una hoja por caja; de lo demás, la planilla de siempre. -->
  <a class="btn btn-tonal" href={inventoryUrl(applied)} download>
    <Icono nombre="descargar" />
    Descargar inventario (Excel)
  </a>
</section>

{#if loading && !rows.length}
  <p class="muted">Cargando…</p>
{:else if !rows.length}
  <p class="muted">
    {applied ? `Nada coincide con «${applied}».` : 'Todavía no se generó ningún PDF.'}
  </p>
{:else}
  {#if resolutions && resolutions.total > rows.length}
    <p class="muted small">
      Mostrando {rows.length} de {resolutions.total}. Refine la búsqueda para ver el resto.
    </p>
  {/if}

  <div class="panel panel-flush table-wrap">
    <table>
      <thead>
        <tr>
          <th>N° / código</th>
          <th>Tipo</th>
          <th>Título</th>
          <th>Documento de origen</th>
          <th>Operador</th>
          <th>Páginas</th>
          <th><span class="sr-only">Acciones</span></th>
        </tr>
      </thead>
      <tbody>
        {#each rows as row (keyOf(row))}
          <tr>
            {#if editing === keyOf(row)}
              <td colspan="7" class="editor">
                <div class="fields">
                  <label>
                    <span>Número</span>
                    <input
                      class="input input-sm mono code-input"
                      bind:value={draftCode}
                      spellcheck="false"
                      aria-invalid={faltaElCodigo}
                    />
                  </label>
                  <label class="grow">
                    <span>Título</span>
                    <input
                      class="input input-sm"
                      bind:value={draftTitle}
                      placeholder="obligatorio"
                      aria-invalid={faltaElTitulo}
                    />
                  </label>
                  <button
                    class="btn btn-primary btn-sm"
                    onclick={() => saveRow(row)}
                    disabled={!puedeGuardarLaFila}
                  >
                    {rowBusy ? 'Guardando…' : 'Guardar'}
                  </button>
                  <button
                    class="btn btn-danger btn-sm"
                    onclick={() => removeRow(row)}
                    disabled={rowBusy}
                  >
                    Eliminar
                  </button>
                  <button
                    class="btn btn-ghost btn-sm"
                    onclick={() => (editing = null)}
                    disabled={rowBusy}
                  >
                    Cancelar
                  </button>
                </div>
                {#if faltaElCodigo || faltaElTitulo}
                  <p class="falta inline">
                    Falta {faltaElCodigo && faltaElTitulo
                      ? 'el número y el título'
                      : faltaElCodigo
                        ? 'el número'
                        : 'el título'}. Una corrección se manda entera.
                  </p>
                {/if}
                {#if rowError}<p class="inline-error">{rowError}</p>{/if}
              </td>
            {:else}
              <td class="mono">{row.code}</td>
              <!-- El tipo documental. Vacío es una respuesta: un tercio de una
                   caja real no lleva rótulo legible, y la raya dice que nadie
                   lo reconoció en vez de fingir que sí. -->
              <td class="dim">{row.type ?? '—'}</td>
              <td class="dim">{row.title ?? '—'}</td>
              <td class="dim">{row.source_document}</td>
              <td class="dim">{row.operator ?? '—'}</td>
              <td class="mono">
                {row.pages} <span class="muted">({row.page_count})</span>
                <!-- Qué páginas de esta unidad son anexos. Sin esto, un acta
                     con sus cuatro fotografías se lee como un acta de cinco
                     hojas. -->
                {#if row.attachments}
                  <span class="muted">· anexos {row.attachments}</span>
                {/if}
              </td>
              <td class="tools">
                <button class="btn btn-ghost btn-sm" onclick={() => edit(row)}>Editar</button>
                <a
                  class="btn btn-icon"
                  href={downloadUrl(row.job_id, row.file_name)}
                  download
                  title="Descargar PDF"
                  aria-label={`Descargar ${row.file_name}`}
                >
                  <Icono nombre="descargar" />
                </a>
              </td>
            {/if}
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  /* Las cifras, sobre el `.panel` común. */
  .summary {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-4) var(--space-8);
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
  }

  /* La tabla va en un `.panel` sin relleno: las celdas traen el suyo. */
  .table-wrap {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  thead th {
    padding: 0.7rem 0.75rem;
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
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
    font-size: var(--text-xs);
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
    font-size: var(--text-xs);
  }

  .tools {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.25rem;
    white-space: nowrap;
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
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
    text-transform: uppercase;
    color: var(--muted);
  }
  .code-input {
    width: 9rem;
  }

  /* Lo que falta no es un error: nadie se ha equivocado todavía. Va en el tono
     apagado del resto de las indicaciones, no en el del fallo. */
  .falta.inline {
    margin: 0.5rem 0 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }
</style>
