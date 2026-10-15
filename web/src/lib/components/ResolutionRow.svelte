<script lang="ts">
  import { deleteOutput, downloadUrl, renameOutput } from '$lib/api';
  import Icono from '$lib/components/Icono.svelte';
  import type { Group } from '$lib/types';

  interface Props {
    jobId: string;
    group: Group;
    /** The file the assembler actually wrote, if it is still on disk. */
    fileName?: string;
    pageRange: string;
    /** Called after a successful edit or delete, so the page can refresh. */
    onchange?: () => void;
  }

  let { jobId, group, fileName, pageRange, onchange }: Props = $props();

  // Qué clase de papel es, cuando alguien lo reconoció. "DOCUMENTO" es lo que
  // se escribe cuando nadie lo reconoció, y eso no es un tipo que enseñar: la
  // fila muestra entonces la procedencia, como hacía antes de que existieran
  // los tipos.
  const kind = $derived(
    group.type && group.type !== 'DOCUMENTO' ? group.type : null
  );

  type Mode = 'idle' | 'editing' | 'confirming';
  let mode = $state<Mode>('idle');
  let busy = $state(false);
  let error = $state<string | null>(null);

  // Seeded when the editor opens, not at construction: the row re-renders from
  // the server after a save, and a field frozen at the first value would show
  // the old number back to the operator who just corrected it.
  let code = $state('');
  let title = $state('');

  /**
   * Qué hace falta para poder guardar: los dos campos, siempre.
   *
   * Vale para todos los perfiles. Una corrección se manda entera o no se manda:
   * un título en blanco no es una decisión, es un campo que se quedó sin
   * llenar, y se queda así para siempre porque nadie vuelve sobre un documento
   * que ya salió. La misma regla rige en los demás formularios del programa.
   */
  const faltaElNumero = $derived(!code.trim());
  const faltaElTitulo = $derived(!title.trim());
  const puedeGuardar = $derived(!busy && !faltaElNumero && !faltaElTitulo);

  function edit() {
    // Reset from the group each time: an abandoned edit must not come back.
    code = group.code;
    title = group.title ?? '';
    error = null;
    mode = 'editing';
  }

  async function save() {
    // La misma guarda que apaga el botón, otra vez aquí: el botón se puede
    // pulsar con el teclado antes de que la pantalla repinte, y la regla tiene
    // que estar donde se ejecuta la acción y no sólo donde se dibuja.
    if (!fileName || !puedeGuardar) return;
    busy = true;
    error = null;
    try {
      await renameOutput(jobId, fileName, { code: code.trim(), title: title.trim() || null });
      mode = 'idle';
      onchange?.();
    } catch (problem) {
      error = (problem as Error).message;
    } finally {
      busy = false;
    }
  }

  async function remove() {
    if (!fileName) return;
    busy = true;
    error = null;
    try {
      await deleteOutput(jobId, fileName);
      mode = 'idle';
      onchange?.();
    } catch (problem) {
      error = (problem as Error).message;
      mode = 'idle';
    } finally {
      busy = false;
    }
  }
</script>

<tr class="row">
  {#if mode === 'editing'}
    <td colspan="6" class="editor">
      <div class="fields">
        <label>
          <span class="caps">Número</span>
          <input
            class="input input-sm mono code"
            bind:value={code}
            spellcheck="false"
            aria-invalid={faltaElNumero}
          />
        </label>
        <label class="grow">
          <span class="caps">Título</span>
          <input
            class="input input-sm"
            bind:value={title}
            placeholder="obligatorio"
            aria-invalid={faltaElTitulo}
          />
        </label>
      </div>
      <div class="actions">
        <button class="btn btn-primary btn-sm" onclick={save} disabled={!puedeGuardar}>
          {busy ? 'Guardando…' : 'Guardar'}
        </button>
        <button class="btn btn-ghost btn-sm" onclick={() => (mode = 'idle')} disabled={busy}>
          Cancelar
        </button>
      </div>
      {#if faltaElNumero || faltaElTitulo}
        <p class="falta">
          Falta {faltaElNumero && faltaElTitulo
            ? 'el número y el título'
            : faltaElNumero
              ? 'el número'
              : 'el título'}. Una corrección se manda entera.
        </p>
      {/if}
      {#if error}<p class="inline-error">{error}</p>{/if}
    </td>
  {:else if mode === 'confirming'}
    <td colspan="6" class="editor">
      <p class="warn">
        Se eliminará <b>{fileName}</b> y su registro en el inventario. No se puede deshacer.
      </p>
      <div class="actions">
        <button class="btn btn-danger btn-sm" onclick={remove} disabled={busy}>
          {busy ? 'Eliminando…' : 'Sí, eliminar'}
        </button>
        <button class="btn btn-ghost btn-sm" onclick={() => (mode = 'idle')} disabled={busy}>
          Cancelar
        </button>
      </div>
    </td>
  {:else}
    <td class="code-cell">{group.code}</td>
    <td class="title-cell">
      <!-- El tipo delante y la procedencia debajo: lo primero que se busca en
           esta tabla es qué es cada documento, y de dónde salió es lo que se
           mira después, cuando hay que volver al PDF a comprobar un corte. -->
      {#if kind}
        <span class="kind">{kind}</span>
        <span class="origin">{group.title ?? ''}</span>
      {:else}
        {group.title ?? '—'}
      {/if}
    </td>
    <td class="pages-cell">
      {pageRange}
      <span class="muted">({group.size})</span>
    </td>
    <td class="date-cell">{group.fecha ?? '—'}</td>
    <!-- Cómo se llama en el disco. La tabla enseñaba el número, el asunto y
         las páginas de cada unidad, y no su nombre de archivo: para saber cuál
         de los treinta PDF de la carpeta era cuál había que abrirlos. -->
    <td class="file-cell">{fileName ? fileName.split('/').pop() : '—'}</td>
    <td class="tools">
      {#if fileName}
        <!-- Los mismos botones de fila que el archivo: editar en fantasma,
             eliminar en peligro y la descarga como icono, que se reconoce
             antes de leerse y deja el ancho para el número y el título. -->
        <button class="btn btn-ghost btn-sm" onclick={edit} title="Corregir número o título">
          Editar
        </button>
        <button
          class="btn btn-danger btn-sm"
          onclick={() => (mode = 'confirming')}
          title="Eliminar el PDF"
        >
          Eliminar
        </button>
        <a
          class="btn btn-icon"
          href={downloadUrl(jobId, fileName)}
          download
          title="Descargar PDF"
          aria-label={`Descargar ${fileName}`}
        >
          <Icono nombre="descargar" />
        </a>
      {:else}
        <span class="muted">Sin archivo</span>
      {/if}
      {#if error}<span class="error-fila">{error}</span>{/if}
    </td>
  {/if}
</tr>

<style>
  .row {
    border-top: 1px solid var(--hairline);
  }

  td {
    padding: 0.4rem 0.75rem 0.4rem 0;
    font-size: var(--text-sm);
    vertical-align: baseline;
  }

  .code-cell {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    white-space: nowrap;
  }
  .title-cell {
    color: var(--ink-2);
  }
  .kind {
    display: block;
    color: var(--ink);
  }
  .origin {
    display: block;
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .date-cell {
    font-variant-numeric: tabular-nums;
    color: var(--muted);
    white-space: nowrap;
  }
  .file-cell {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--ink-2);
    word-break: break-all;
  }
  .pages-cell {
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .muted {
    color: var(--muted);
  }

  .tools {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.25rem;
    padding-right: 0;
    white-space: nowrap;
  }

  .editor {
    background: var(--plane);
    padding: 0.7rem 0.75rem;
  }
  .fields {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
  }
  .fields label {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }
  .fields .grow {
    flex: 1;
    min-width: 14rem;
  }
  .code {
    width: 9rem;
  }

  .actions {
    display: flex;
    gap: 0.4rem;
    margin-top: 0.6rem;
  }

  .warn {
    margin: 0;
    font-size: var(--text-md);
    color: var(--ink-2);
  }
  .warn b {
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }

  /* Lo que falta no es un error: nadie se ha equivocado, sólo no ha terminado
     de escribir. Apagado, como el resto de las indicaciones. */
  .falta {
    margin: 0.4rem 0 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .error-fila {
    font-size: var(--text-xs);
    color: var(--critical);
  }
</style>
