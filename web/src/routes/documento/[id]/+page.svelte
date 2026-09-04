<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import {
    documentFuidUrl,
    downloadUrl,
    fetchDocument,
    renameJob,
    type ArchivedDocument
  } from '$lib/api';
  import { formatBytes } from '$lib/format';
  import JobCard from '$lib/components/JobCard.svelte';
  import ValidationPanel from '$lib/components/ValidationPanel.svelte';
  import { jobStore } from '$lib/jobs.svelte';
  import type { InventoryReport } from '$lib/types';

  const job = $derived(jobStore.get(page.params.id ?? ''));

  /**
   * El mismo documento, pero recordado por el inventario.
   *
   * La ficha se dibujaba sólo desde el trabajo en memoria, así que en cuanto el
   * área de trabajo se limpiaba el documento quedaba en un callejón sin salida:
   * decía "archivado" y no llevaba a ninguna parte. El inventario sí lo
   * recuerda, y esto es lo que se enseña cuando ya no está en pantalla.
   */
  let archived = $state<ArchivedDocument | null>(null);
  let loadingArchived = $state(false);
  let archivedError = $state<string | null>(null);

  $effect(() => {
    const id = page.params.id ?? '';
    if (!id || job) return;
    loadingArchived = true;
    archivedError = null;
    fetchDocument(id)
      .then((found) => (archived = found))
      .catch((problem) => (archivedError = (problem as Error).message))
      .finally(() => (loadingArchived = false));
  });

  /**
   * El informe de un trabajo de inventario, que tiene otra forma que el de una
   * división: no trae grupos ni salidas, trae el tipo reconocido y las filas.
   */
  const inventory = $derived.by(() => {
    // Por la forma del informe y no por la acción: "dividir e inventariar"
    // produce los dos, y un libro de folios dividido también trae el tipo
    // reconocido y sus registros.
    const report = job?.report as unknown as InventoryReport | null;
    return report?.document_type ? report : null;
  });

  /** El FUID existe cuando la acción lo incluía y se pudo escribir. */
  const fuid = $derived(job?.report?.fuid ?? inventory?.fuid ?? null);
  const fuidError = $derived(job?.report?.fuid_error ?? inventory?.fuid_error ?? null);

  /**
   * Cómo se llama en pantalla lo que el sistema reconoció. Se muestra en las
   * dos acciones: al dividir importa igual, porque el tipo es lo que decide con
   * qué regla se parte y con qué columnas se inventaría.
   */
  const TIPOS: Record<string, string> = {
    resolucion: 'Resoluciones',
    diploma: 'Registro de diplomas',
    matricula: 'Registros de matrícula',
    desconocido: 'Sin identificar'
  };

  const recognised = $derived.by(() => {
    if (inventory) {
      return { label: inventory.document_type_label, confidence: inventory.type_confidence };
    }
    const stats = job?.report?.stats;
    if (!stats?.document_type) return null;
    return { label: TIPOS[stats.document_type] ?? stats.document_type, confidence: stats.type_confidence ?? 0 };
  });
  let confirmingDelete = $state(false);
  let renaming = $state(false);
  let draft = $state('');
  let error = $state<string | null>(null);

  async function rename() {
    const name = draft.trim();
    if (!name) return;
    try {
      await renameJob(page.params.id ?? '', name);
      renaming = false;
    } catch (problem) {
      error = (problem as Error).message;
    }
  }

  async function remove(purge: boolean) {
    confirmingDelete = false;
    try {
      await jobStore.remove(page.params.id ?? '', purge);
      await goto('/');
    } catch (problem) {
      error = (problem as Error).message;
    }
  }
</script>

<nav class="mb-5 flex flex-wrap items-center justify-between gap-3">
  <a class="font-mono text-sm text-accent hover:underline" href="/">← todos los documentos</a>

  {#if job}
    {#if renaming}
      <span class="flex flex-wrap items-center gap-2">
        <input
          class="min-w-64 rounded border border-hairline bg-raised px-2 py-1 text-sm outline-none focus:border-accent"
          bind:value={draft}
        />
        <button class="rounded border border-accent px-2.5 py-1 text-xs text-accent" onclick={rename}>
          Guardar
        </button>
        <button
          class="rounded border border-hairline px-2.5 py-1 text-xs text-muted"
          onclick={() => (renaming = false)}
        >
          Cancelar
        </button>
      </span>
    {:else if confirmingDelete}
      <span class="flex flex-wrap items-center gap-2 text-sm">
        <button
          class="rounded border border-hairline px-2.5 py-1 text-xs"
          onclick={() => remove(false)}
        >
          Quitar de la pantalla
        </button>
        <button
          class="rounded border border-critical px-2.5 py-1 text-xs text-critical hover:bg-critical hover:text-white"
          onclick={() => remove(true)}
        >
          Eliminar también los PDF
        </button>
        <button
          class="rounded border border-hairline px-2.5 py-1 text-xs text-muted"
          onclick={() => (confirmingDelete = false)}
        >
          Cancelar
        </button>
      </span>
    {:else}
      <span class="flex gap-2">
        <button
          class="rounded border border-hairline px-2.5 py-1 font-mono text-xs text-muted transition-colors hover:border-accent hover:text-accent"
          onclick={() => {
            draft = job?.filename ?? '';
            renaming = true;
          }}
        >
          renombrar
        </button>
        <button
          class="rounded border border-hairline px-2.5 py-1 font-mono text-xs text-muted transition-colors hover:border-critical hover:text-critical"
          onclick={() => (confirmingDelete = true)}
        >
          eliminar
        </button>
      </span>
    {/if}
  {/if}
</nav>

{#if error}
  <p class="mb-4 text-sm text-critical">{error}</p>
{/if}

{#if job}
  {#if job.state === 'done' && (inventory || fuid || fuidError)}
    <!-- Un documento inventariado no deja PDF: lo único que produce es su FUID,
         y sin un sitio desde donde bajarlo la función no está terminada. -->
    <section
      class="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-hairline bg-raised p-4 shadow-[var(--shadow)]"
    >
      <div>
        <h2 class="text-sm font-semibold">Inventario del documento</h2>
        <p class="mt-1 text-sm text-ink-2">
          {#if inventory}
            Reconocido como <b>{inventory.document_type_label}</b>. Se registraron
            <b>{inventory.records}</b>
            {inventory.records === 1 ? 'unidad documental' : 'unidades documentales'}.
            {#if job.task === 'inventory'}
              El PDF de origen quedó entero.
            {/if}
          {:else}
            El inventario del documento, en el formato oficial de la Universidad.
          {/if}
        </p>
      </div>
      {#if fuid}
        <a
          class="rounded border border-accent px-3 py-1.5 font-mono text-xs text-accent transition-colors hover:bg-accent hover:text-raised"
          href={documentFuidUrl(job.id)}
        >
          descargar el FUID
        </a>
      {:else if fuidError}
        <span class="font-mono text-xs text-critical">no se pudo escribir el FUID</span>
      {/if}
    </section>

  {/if}

  {#if !inventory && job.state === 'done' && recognised}
    <section
      class="mb-4 rounded-xl border border-hairline bg-raised p-4 shadow-[var(--shadow)]"
    >
      <h3 class="text-sm font-semibold">Tipo de documento</h3>
      <p class="mt-1 text-sm text-ink-2">
        El sistema lo reconoció como <b>{recognised.label}</b> por lo que está impreso en sus
        páginas —no por el nombre del archivo—, con una confianza de
        <span class="font-mono">{(recognised.confidence * 100).toFixed(1)} %</span>.
      </p>
    </section>
  {/if}

  {#if job.state === 'done' && job.report?.validation}
    <div class="mb-4">
      <ValidationPanel validation={job.report.validation} issues={job.report.issues} />
    </div>
  {/if}

  <JobCard {job} />
{:else if loadingArchived}
  <div class="rounded-xl border border-hairline bg-raised p-6 text-sm text-muted">
    Buscándolo en el inventario…
  </div>
{:else if archived}
  <!--
    La ficha de un documento que ya salió del área de trabajo. Enseña lo que el
    inventario guarda, que es lo que se produjo, y dice explícitamente lo que no
    guarda: el reparto por peldaños y la cinta de páginas viven en el informe del
    proceso y no sobreviven a la limpieza. Callarlo sería enseñar una ficha
    incompleta con aspecto de completa.
  -->
  <section class="mb-4 rounded-xl border border-hairline bg-raised p-5 shadow-[var(--shadow)]">
    <header class="flex flex-wrap items-baseline justify-between gap-3">
      <h2 class="text-base font-semibold">{archived.source_document}</h2>
      <span class="font-mono text-xs text-muted">archivado</span>
    </header>

    <dl class="mt-4 flex flex-wrap gap-8">
      <div>
        <dt class="text-[0.7rem] tracking-wide text-muted uppercase">Resoluciones</dt>
        <dd class="tabular text-lg font-semibold">{archived.resolutions}</dd>
      </div>
      <div>
        <dt class="text-[0.7rem] tracking-wide text-muted uppercase">Páginas</dt>
        <dd class="tabular text-lg font-semibold">{archived.source_pages || archived.pages}</dd>
      </div>
      <div>
        <dt class="text-[0.7rem] tracking-wide text-muted uppercase">Tamaño</dt>
        <dd class="tabular text-lg font-semibold">
          {archived.bytes ? formatBytes(archived.bytes) : '—'}
        </dd>
      </div>
      <div>
        <dt class="text-[0.7rem] tracking-wide text-muted uppercase">Requiere revisión</dt>
        <dd class="tabular text-lg font-semibold" class:text-warning={archived.review}>
          {archived.review}
        </dd>
      </div>
      {#if archived.operator}
        <div>
          <dt class="text-[0.7rem] tracking-wide text-muted uppercase">Operador</dt>
          <dd class="text-lg font-semibold">{archived.operator}</dd>
        </div>
      {/if}
    </dl>

    <p class="mt-4 text-sm text-ink-2">
      Esta ficha se dibuja desde el inventario. El reparto por peldaños de lectura y la
      cinta de páginas sólo existen mientras el documento está en el área de trabajo.
    </p>
  </section>

  {#if archived.rows.length}
    <section class="rounded-xl border border-hairline bg-raised p-5 shadow-[var(--shadow)]">
      <h3 class="mb-3 text-sm font-semibold">
        Lo que produjo ({archived.rows.length})
      </h3>
      <div class="overflow-x-auto">
        <table class="w-full border-collapse text-sm">
          <thead>
            <tr class="text-[0.7rem] tracking-wide text-muted uppercase">
              <th class="pb-2 text-left font-medium">Resolución</th>
              <th class="pb-2 text-left font-medium">Título</th>
              <th class="pb-2 text-left font-medium">Páginas</th>
              <th class="pb-2 text-right font-medium">Archivo</th>
            </tr>
          </thead>
          <tbody>
            {#each archived.rows as row (row.file_name)}
              <tr class="border-t border-hairline">
                <td class="py-1.5 pr-3 font-mono">{row.code}</td>
                <td class="py-1.5 pr-3 text-ink-2">{row.title ?? '—'}</td>
                <td class="tabular py-1.5 pr-3 text-muted">{row.pages}</td>
                <td class="py-1.5 text-right">
                  <a
                    class="icon-link"
                    href={downloadUrl(row.job_id, row.file_name)}
                    download
                    title={`Descargar ${row.file_name}`}
                    aria-label={`Descargar ${row.file_name}`}
                  >
                    <svg viewBox="0 0 16 16" aria-hidden="true">
                      <path d="M8 2v7m0 0 3-3m-3 3L5 6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
                      <path d="M3 11.5v1A1.5 1.5 0 0 0 4.5 14h7a1.5 1.5 0 0 0 1.5-1.5v-1" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
                    </svg>
                  </a>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>
  {/if}
{:else}
  <div class="rounded-xl border border-hairline bg-raised shadow-[var(--shadow)] p-6">
    <h2 class="text-base font-semibold">Este documento no está en el inventario</h2>
    <p class="mt-1.5 text-sm text-ink-2">
      {archivedError ?? 'No se encontró ni en el área de trabajo ni en el registro.'}
      Puede haberse eliminado. Lo que sí quedó está en el
      <a class="text-accent hover:underline" href="/archivo">archivo</a>.
    </p>
  </div>
{/if}


<style>
  /* Un icono en lugar de la palabra: se reconoce antes y no se lee. El área
     pinchable sigue siendo la de un botón, que es lo que la hace usable. */
  .icon-link {
    display: inline-grid;
    place-items: center;
    width: 1.85rem;
    height: 1.85rem;
    border-radius: 0.35rem;
    color: var(--muted);
    transition:
      color 0.15s,
      background 0.15s;
  }

  .icon-link:hover {
    color: var(--accent);
    background: var(--plane);
  }

  .icon-link svg {
    width: 1rem;
    height: 1rem;
  }
</style>
