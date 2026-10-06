<script lang="ts">
  import { deleteDocument, renameDocument } from '$lib/api';
  import ArchivosDelTrabajo from '$lib/components/archivo/ArchivosDelTrabajo.svelte';
  import { unidades } from '$lib/archive.svelte';
  import { formatBytes } from '$lib/format';
  import { jobStore } from '$lib/jobs.svelte';
  import type { Origen } from '$lib/types';

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
    /**
     * Si es un acta de consejo. Sólo esas tarjetas llevan el botón del
     * inventario de actas: las de resoluciones tienen el suyo, con su formato,
     * en la ficha del documento.
     */
    acta?: boolean;
    /**
     * La carpeta local o el lote del que salió. Con él, el Archivo lo dibuja
     * dentro de la tarjeta de su carpeta y no suelto con su propio nombre.
     */
    origen?: Origen | null;
    /** Los tipos documentales que salieron, para nombrar bien sus unidades. */
    tipos?: string[];
  }

  interface Props {
    entry: Entry;
    /** Called after a successful rename or delete, so the page can reload. */
    onchange?: () => void;
    /**
     * Si la tarjeta está marcada, cuando la lista permite marcar varias.
     *
     * Ausente significa que no hay selección en marcha, y entonces la casilla
     * no se dibuja: una casilla que no sirve para nada ocupa el mismo sitio que
     * una que sí, y en una lista de doscientas tarjetas eso se nota.
     */
    selected?: boolean;
    /** Marcar o desmarcar esta tarjeta. Sin esto no hay casilla. */
    onselect?: (jobId: string, shift: boolean) => void;
  }

  let { entry, onchange, selected, onselect }: Props = $props();

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

  /** «Actas», «Resoluciones» o «Documentos», según qué papel era. */
  const unidad = $derived(unidades(entry.tipos ?? [], entry.acta));

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

  /** Si la tarjeta enseña su inventario y los PDF que dejó. */
  let abierta = $state(false);

  async function remove() {
    busy = true;
    failure = null;
    try {
      await deleteDocument(entry.jobId);
      // Un documento borrado no puede seguir pendiente de revisión: la copia
      // que Revisión conserva de él se suelta con el documento.
      jobStore.forget(entry.jobId);
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

<div
  class="card"
  class:failed={entry.failed}
  class:openable={entry.live && mode === 'idle'}
  class:picking={!!onselect}
  class:open={abierta}
>
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
        {unidad.toLowerCase()} de
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
    <!-- Cerrada es una tarjeta más de la rejilla. Abierta ocupa la fila y se
         parte en dos: el documento a la izquierda y lo que dejó a la derecha,
         en vez de una columna estirada con todo centrado. -->
    <div class="layout" class:split={abierta}>
      <div class="summary">
      {#if onselect}
        <!--
          Fuera del enlace a propósito: dentro, marcar la casilla navegaría al
          detalle del documento y el operador perdería la selección entera.
        -->
        <label class="pick" title="Seleccionar para eliminar en lote">
          <input
            type="checkbox"
            checked={selected ?? false}
            onclick={(event) => onselect(entry.jobId, event.shiftKey)}
          />
          <span class="sr">Seleccionar {entry.name}</span>
        </label>
      {/if}
      <!--
        Lleva al detalle esté en pantalla o archivado. Antes sólo era un enlace
        mientras el trabajo seguía en memoria, así que en cuanto se limpiaba el
        área de trabajo la ficha dejaba de poder abrirse: la tarjeta se veía
        pinchable y no llevaba a ninguna parte.
      -->
      <a class="body" href={`/documento/${entry.jobId}`}>
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
              <dt>{unidad}</dt>
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
      </a>

        {#if !entry.failed}
          <!-- Fuera del enlace: dentro, pulsarlo abriría el detalle. -->
          <button
            class="toggle"
            aria-expanded={abierta}
            aria-controls={`archivos-${entry.jobId}`}
            onclick={() => (abierta = !abierta)}
          >
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3.5 4.5 4.5L6 12.5" /></svg>
            {#if abierta}
              Ocultar archivos
            {:else}
              {entry.acta ? 'Inventario y PDF divididos' : 'Archivos generados'}
            {/if}
          </button>
        {/if}

      <footer>
        {#if entry.operator}
          <span class="by">{entry.operator}</span>
        {:else}
          <span class="by anon">sin operador</span>
        {/if}

        {#if entry.review}
          <span class="review" title={`${entry.review} páginas requieren revisión`}>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M8 2.5 14 13H2L8 2.5Z" />
              <path d="M8 6.5v3M8 11.3v.2" />
            </svg>
            {entry.review}
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
          <!--
            Un solo enlace, esté el documento en pantalla o archivado: desde que
            la ficha se dibuja también desde el inventario, los dos abren. Poner
            además el rótulo "archivado" metía un elemento de más en un pie que no
            reparte, y la fila se salía de la tarjeta.
          -->
          <a class="open" href={`/documento/${entry.jobId}`} title={entry.live ? undefined : 'Archivado: se dibuja desde el inventario'}>
            ver detalle
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3.5 4.5 4.5L6 12.5" /></svg>
          </a>
        </span>
      </footer>

        {#if failure}<p class="error">{failure}</p>{/if}
      </div>

      {#if abierta && !entry.failed}
        <section class="detail" id={`archivos-${entry.jobId}`} aria-label={`Archivos de ${entry.name}`}>
          <ArchivosDelTrabajo jobId={entry.jobId} />
        </section>
      {/if}
    </div>
  {/if}
</div>

<style>
  /* La casilla se apoya sobre la esquina de la tarjeta sin empujar nada. */
  .pick {
    position: absolute;
    top: 0.55rem;
    left: 0.55rem;
    z-index: 2;
    display: grid;
    place-items: center;
    padding: 0.15rem;
    cursor: pointer;
  }

  .pick input {
    width: 1rem;
    height: 1rem;
    cursor: pointer;
    accent-color: var(--accent);
  }

  /*
    La casilla flota sobre la esquina, así que el nombre tiene que apartarse o
    queda debajo. Se aparta sólo el renglón del título -- las cifras y el pie
    siguen usando el ancho entero -- porque es la única línea que llega hasta
    ese borde.
  */
  .card.picking header {
    padding-left: 1.55rem;
  }

  /* Sólo para quien lee la pantalla en voz alta. */
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }

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

  /* Abierta ocupa la fila entera: la lista de PDF de un libro no cabe en una
     columna de la rejilla. */
  .card.open {
    grid-column: 1 / -1;
    container-type: inline-size;
  }

  .layout,
  .summary {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 0.6rem;
  }

  /* De borde a borde de la tarjeta: sin esto la rejilla se encogía a su
     contenido y quedaba centrada en la fila, con el resumen flotando. */
  .layout {
    width: 100%;
    align-self: stretch;
  }

  .detail {
    min-width: 0;
    border-top: 1px solid var(--rule);
    padding-top: 0.85rem;
  }

  /* Con sitio, el documento a la izquierda y sus archivos a la derecha. */
  @container (min-width: 46rem) {
    .layout.split {
      display: grid;
      grid-template-columns: minmax(15rem, 19rem) minmax(0, 1fr);
      align-items: start;
      gap: 1.5rem;
    }
    .layout.split .detail {
      border-top: 0;
      border-left: 1px solid var(--rule);
      padding: 0 0 0 1.5rem;
    }
  }

  .toggle {
    display: inline-flex;
    align-self: flex-start;
    align-items: center;
    gap: 0.25rem;
    border: 0;
    background: none;
    padding: 0;
    font: inherit;
    font-size: 0.74rem;
    font-weight: 600;
    color: var(--accent);
    cursor: pointer;
  }
  .toggle:hover {
    text-decoration: underline;
  }
  .toggle svg {
    width: 0.85rem;
    height: 0.85rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.6;
    stroke-linecap: round;
    stroke-linejoin: round;
    transition: transform 0.15s ease;
  }
  .toggle[aria-expanded='true'] svg {
    transform: rotate(90deg);
  }

  footer {
    display: flex;
    /* Que reparta antes que desbordar: la tarjeta tiene un ancho fijo en la
       rejilla y un pie que no se rompe se sale por el borde. */
    flex-wrap: wrap;
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
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 0.2rem;
    border-radius: 999px;
    background: color-mix(in oklab, var(--warning) 16%, transparent);
    padding: 0 0.4rem;
    font-family: var(--font-mono);
    font-size: 0.66rem;
    color: var(--warning);
  }

  .review svg,
  .open svg {
    width: 0.75rem;
    height: 0.75rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.6;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .open {
    display: inline-flex;
    align-items: center;
    gap: 0.1rem;
    font-size: 0.7rem;
    text-decoration: none;
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
