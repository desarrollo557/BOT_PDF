<script lang="ts">
  import { deleteOutput, downloadUrl, renameOutput } from '$lib/api';
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

  function edit() {
    // Reset from the group each time: an abandoned edit must not come back.
    code = group.code;
    title = group.title ?? '';
    error = null;
    mode = 'editing';
  }

  async function save() {
    if (!fileName) return;
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
          <span>Número</span>
          <input class="code" bind:value={code} spellcheck="false" />
        </label>
        <label class="grow">
          <span>Título</span>
          <input bind:value={title} placeholder="sin título" />
        </label>
      </div>
      <div class="actions">
        <button class="primary" onclick={save} disabled={busy || !code.trim()}>
          {busy ? 'guardando…' : 'guardar'}
        </button>
        <button onclick={() => (mode = 'idle')} disabled={busy}>cancelar</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </td>
  {:else if mode === 'confirming'}
    <td colspan="6" class="editor">
      <p class="warn">
        Se eliminará <b>{fileName}</b> y su registro en el inventario. No se puede deshacer.
      </p>
      <div class="actions">
        <button class="danger" onclick={remove} disabled={busy}>
          {busy ? 'eliminando…' : 'sí, eliminar'}
        </button>
        <button onclick={() => (mode = 'idle')} disabled={busy}>cancelar</button>
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
        <a
          class="icon-link"
          href={downloadUrl(jobId, fileName)}
          download
          title={`Descargar ${fileName}`}
          aria-label={`Descargar ${fileName}`}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M8 2v7m0 0 3-3m-3 3L5 6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M3 11.5v1A1.5 1.5 0 0 0 4.5 14h7a1.5 1.5 0 0 0 1.5-1.5v-1" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
          </svg>
        </a>
        <button onclick={edit} title="Corregir número o título">editar</button>
        <button class="quiet" onclick={() => (mode = 'confirming')} title="Eliminar el PDF">
          eliminar
        </button>
      {:else}
        <span class="muted">sin archivo</span>
      {/if}
      {#if error}<span class="error inline">{error}</span>{/if}
    </td>
  {/if}
</tr>

<style>
  /* El icono dice "descargar" sin escribirlo, y deja el ancho de la columna
     para lo que sí hay que leer: el número y el título de la resolución. */
  .icon-link {
    display: inline-grid;
    place-items: center;
    width: 1.7rem;
    height: 1.7rem;
    border-radius: 0.3rem;
    color: var(--muted);
    vertical-align: middle;
    transition:
      color 0.15s,
      background 0.15s;
  }

  .icon-link:hover {
    color: var(--accent);
    background: var(--plane);
  }

  .icon-link svg {
    width: 0.95rem;
    height: 0.95rem;
  }

  .row {
    border-top: 1px solid var(--hairline);
  }

  td {
    padding: 0.5rem 0.75rem 0.5rem 0;
    vertical-align: baseline;
  }

  .code-cell {
    font-family: var(--font-mono);
    font-size: 0.75rem;
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
    font-size: 0.75rem;
    color: var(--muted);
  }
  .date-cell {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    color: var(--muted);
    white-space: nowrap;
  }
  .file-cell {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--ink-2);
    word-break: break-all;
  }
  .pages-cell {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .muted {
    color: var(--muted);
  }

  .tools {
    display: flex;
    justify-content: flex-end;
    gap: 0.6rem;
    padding-right: 0;
    text-align: right;
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
    font-size: 0.8rem;
    color: var(--muted);
    cursor: pointer;
  }
  .tools button:hover {
    color: var(--ink);
  }
  .tools button.quiet:hover {
    color: var(--critical);
  }

  .editor {
    padding: 0.7rem 0;
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
    background: var(--plane);
    padding: 0.35rem 0.55rem;
    font: inherit;
    font-size: 0.85rem;
    color: inherit;
    outline: none;
  }
  .fields input:focus {
    border-color: var(--accent);
  }
  .fields .code {
    width: 9rem;
    font-family: var(--font-mono);
    font-size: 0.8rem;
  }

  .actions {
    display: flex;
    gap: 0.4rem;
    margin-top: 0.6rem;
  }
  .actions button {
    border: 1px solid var(--hairline);
    border-radius: 7px;
    background: transparent;
    padding: 0.25rem 0.7rem;
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--muted);
    cursor: pointer;
  }
  .actions button.primary {
    border-color: var(--accent);
    color: var(--accent);
  }
  .actions button.danger {
    border-color: var(--critical);
    color: var(--critical);
  }
  .actions button.danger:hover {
    background: var(--critical);
    color: #fff;
  }
  .actions button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .warn {
    margin: 0;
    font-size: 0.85rem;
    color: var(--ink-2);
  }
  .warn b {
    font-family: var(--font-mono);
    font-size: 0.8rem;
  }

  .error {
    margin: 0.45rem 0 0;
    font-size: 0.8rem;
    color: var(--critical);
  }
  .error.inline {
    margin: 0;
    font-size: 0.72rem;
  }
</style>
