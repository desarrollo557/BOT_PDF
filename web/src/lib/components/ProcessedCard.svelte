<script lang="ts">
  import { deleteDocument, renameDocument } from '$lib/api';
  import { formatBytes } from '$lib/format';

  /**
   * One processed document, however it is being remembered.
   *
   * Live jobs and ledger history used to render as two different things -- tiles
   * and a row of code chips -- so the same document looked like two kinds of
   * object depending on how recently it ran. One card for both, and the codes
   * are gone: a fistful of numbers with no room to say what they mean is noise,
   * and the "por resolución" grain already lists them properly.
   */
  export interface Entry {
    key: string;
    jobId: string;
    name: string;
    at: number;
    resolutions: number;
    pages: number;
    bytes: number;
    review: number;
    operator: string | null;
    /** The resolution numbers it produced. Searched, never drawn on the card. */
    codes: string[];
    failed: boolean;
    error: string | null;
    /** Whether the full report is still on screen, so it can be opened. */
    live: boolean;
  }

  interface Props {
    entry: Entry;
    /** Called after a successful rename or delete, so the page can reload. */
    onchange?: () => void;
  }

  let { entry, onchange }: Props = $props();

  /**
   * The card is a folder, an editor or a warning -- never two at once.
   *
   * A rename field tucked into a corner of the card would sit next to a
   * clickable surface that navigates away, and the operator would lose what
   * they typed by missing the input by four pixels.
   */
  type Mode = 'idle' | 'renaming' | 'confirming';
  let mode = $state<Mode>('idle');
  let busy = $state(false);
  let failure = $state<string | null>(null);
  let draft = $state('');

  const clock = $derived(
    new Date(entry.at).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })
  );

  function startRename() {
    // Seeded from the entry each time the editor opens: an abandoned edit must
    // not come back the next time somebody clicks "renombrar".
    draft = entry.name;
    failure = null;
    mode = 'renaming';
  }

  async function save() {
    const name = draft.trim();
    if (!name || name === entry.name) {
      mode = 'idle';
      return;
    }
    busy = true;
    failure = null;
    try {
      await renameDocument(entry.jobId, name);
      mode = 'idle';
      onchange?.();
    } catch (problem) {
      failure = (problem as Error).message;
    } finally {
      busy = false;
    }
  }

  async function remove() {
    busy = true;
    failure = null;
    try {
      await deleteDocument(entry.jobId);
      mode = 'idle';
      onchange?.();
    } catch (problem) {
      failure = (problem as Error).message;
      mode = 'idle';
    } finally {
      busy = false;
    }
  }
</script>

<div class="card" class:failed={entry.failed} class:openable={entry.live && mode === 'idle'}>
  <span class="tab" aria-hidden="true"></span>

  {#if mode === 'renaming'}
    <div class="panel">
      <label>
        <span>Nombre del documento</span>
        <!-- svelte-ignore a11y_autofocus -->
        <input
          bind:value={draft}
          autofocus
          spellcheck="false"
          onkeydown={(event) => {
            if (event.key === 'Enter') save();
            if (event.key === 'Escape') mode = 'idle';
          }}
        />
      </label>
      <p class="note">
        Cambia el nombre en el inventario y en la pantalla. Los PDF generados
        conservan el suyo, que sale del número de resolución.
      </p>
      <div class="actions">
        <button class="primary" onclick={save} disabled={busy || !draft.trim()}>
          {busy ? 'guardando…' : 'guardar'}
        </button>
        <button onclick={() => (mode = 'idle')} disabled={busy}>cancelar</button>
      </div>
      {#if failure}<p class="error">{failure}</p>{/if}
    </div>
  {:else if mode === 'confirming'}
    <div class="panel">
      <p class="warn">
        Se eliminarán <b>{entry.resolutions}</b>
        {entry.resolutions === 1 ? 'resolución' : 'resoluciones'} de
        <b>{entry.name}</b>: los PDF generados y sus filas del inventario. No se puede
        deshacer.
      </p>
      <div class="actions">
        <button class="danger" onclick={remove} disabled={busy}>
          {busy ? 'eliminando…' : 'sí, eliminar'}
        </button>
        <button onclick={() => (mode = 'idle')} disabled={busy}>cancelar</button>
      </div>
      {#if failure}<p class="error">{failure}</p>{/if}
    </div>
  {:else}
    <svelte:element
      this={entry.live ? 'a' : 'div'}
      class="body"
      href={entry.live ? `/documento/${entry.jobId}` : undefined}
    >
      <header>
        <span class="name" title={entry.name}>{entry.name}</span>
        <time class="tabular">{clock}</time>
      </header>

      {#if entry.failed}
        <p class="error" title={entry.error ?? ''}>{entry.error ?? 'No se pudo procesar'}</p>
      {:else}
        <!-- Two numbers, always in the same place, always meaning the same thing. -->
        <dl class="figures">
          <div>
            <dt>Resoluciones</dt>
            <dd class="tabular">{entry.resolutions}</dd>
          </div>
          <div>
            <dt>Páginas</dt>
            <dd class="tabular">{entry.pages || '—'}</dd>
          </div>
          <div>
            <dt>Tamaño</dt>
            <dd class="tabular">{entry.bytes ? formatBytes(entry.bytes) : '—'}</dd>
          </div>
        </dl>
      {/if}
    </svelte:element>

    <footer>
      {#if entry.operator}
        <span class="by">{entry.operator}</span>
      {:else}
        <span class="by anon">sin operador</span>
      {/if}

      {#if entry.review}
        <span class="review" title={`${entry.review} páginas requieren revisión`}>
          ⚠ {entry.review}
        </span>
      {/if}

      <span class="tools">
        <button onclick={startRename} title="Cambiar el nombre del documento">renombrar</button>
        <button
          class="quiet"
          onclick={() => {
            failure = null;
            mode = 'confirming';
          }}
          title="Eliminar el documento, sus PDF y su inventario"
        >
          eliminar
        </button>
        {#if entry.live}
          <a class="open" href={`/documento/${entry.jobId}`}>ver detalle →</a>
        {:else}
          <span class="archived">archivado</span>
        {/if}
      </span>
    </footer>

    {#if failure}<p class="error">{failure}</p>{/if}
  {/if}
</div>

<style>
  /* Drawn as a folder: a finished document is something you open, not a row you
     scroll past. */
  .card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    border: 1px solid var(--hairline);
    border-radius: 4px 10px 10px 10px;
    background: var(--surface-2);
    padding: 0.8rem 0.9rem;
    box-shadow: var(--shadow);
    color: inherit;
    text-decoration: none;
    transition:
      border-color 0.15s,
      transform 0.15s,
      box-shadow 0.15s;
  }
  .card.openable:hover {
    border-color: var(--accent);
    transform: translateY(-1px);
    box-shadow: 0 8px 22px rgb(0 0 0 / 0.12);
  }

  /* The clickable part of the card. The tools live outside it, because a button
     inside a link is neither valid HTML nor predictable to click. */
  .body {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    color: inherit;
    text-decoration: none;
  }

  .tab {
    position: absolute;
    top: -7px;
    left: -1px;
    width: 46px;
    height: 8px;
    border: 1px solid var(--hairline);
    border-bottom: 0;
    border-radius: 4px 6px 0 0;
    background: var(--surface-2);
  }
  .card.failed,
  .card.failed .tab {
    border-color: color-mix(in oklab, var(--critical) 40%, var(--hairline));
  }

  header {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
  }
  .name {
    overflow: hidden;
    flex: 1;
    font-size: 0.86rem;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  time {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--axis);
  }

  .figures {
    display: flex;
    gap: 1.25rem;
    margin: 0;
  }
  .figures div {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .figures dt {
    font-size: 0.58rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .figures dd {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 0.95rem;
    color: var(--ink);
  }

  .error {
    margin: 0;
    overflow: hidden;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--critical);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  footer {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    border-top: 1px solid var(--rule);
    padding-top: 0.5rem;
  }
  .by {
    overflow: hidden;
    max-width: 11rem;
    border-radius: 999px;
    background: var(--accent-soft);
    padding: 0 0.45rem;
    font-size: 0.66rem;
    color: var(--accent);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .by.anon {
    background: transparent;
    padding: 0;
    color: var(--muted);
  }

  .review {
    flex-shrink: 0;
    border-radius: 999px;
    background: color-mix(in oklab, var(--warning) 16%, transparent);
    padding: 0 0.4rem;
    font-family: var(--font-mono);
    font-size: 0.66rem;
    color: var(--warning);
  }

  .tools {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-left: auto;
    flex-shrink: 0;
  }
  .tools button {
    border: 0;
    background: none;
    padding: 0;
    font: inherit;
    font-size: 0.7rem;
    color: var(--muted);
    cursor: pointer;
  }
  .tools button:hover {
    color: var(--ink);
  }
  .tools button.quiet:hover {
    color: var(--critical);
  }

  .open,
  .archived {
    flex-shrink: 0;
    font-size: 0.7rem;
    color: var(--muted);
    text-decoration: none;
  }
  .card.openable:hover .open {
    color: var(--accent);
  }

  /* The editor and the confirmation take the whole card: one thing at a time. */
  .panel {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .panel label {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }
  .panel label span {
    font-size: 0.58rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .panel input {
    border: 1px solid var(--hairline);
    border-radius: 7px;
    background: var(--plane);
    padding: 0.35rem 0.55rem;
    font: inherit;
    font-size: 0.85rem;
    color: inherit;
    outline: none;
  }
  .panel input:focus {
    border-color: var(--accent);
  }
  .note {
    margin: 0;
    font-size: 0.68rem;
    line-height: 1.45;
    color: var(--muted);
  }
  .warn {
    margin: 0;
    font-size: 0.78rem;
    line-height: 1.45;
    color: var(--ink-2);
  }
  .warn b {
    color: var(--ink);
  }

  .actions {
    display: flex;
    gap: 0.4rem;
  }
  .actions button {
    border: 1px solid var(--hairline);
    border-radius: 7px;
    background: transparent;
    padding: 0.25rem 0.7rem;
    font-family: var(--font-mono);
    font-size: 0.7rem;
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
</style>
