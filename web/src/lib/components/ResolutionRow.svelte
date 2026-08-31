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
    <td colspan="4" class="editor">
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
    <td colspan="4" class="editor">
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
    <td class="title-cell">{group.title ?? '—'}</td>
    <td class="pages-cell">
      {pageRange}
      <span class="muted">({group.size})</span>
    </td>
    <td class="tools">
      {#if fileName}
        <a href={downloadUrl(jobId, fileName)} download>PDF</a>
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
