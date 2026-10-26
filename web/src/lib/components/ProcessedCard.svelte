<script lang="ts">
  import { deleteDocument, renameDocument } from '$lib/api';
  import ArchivosDelTrabajo from '$lib/components/archivo/ArchivosDelTrabajo.svelte';
  import Icono from '$lib/components/Icono.svelte';
  import { unidades } from '$lib/archive.svelte';
  import { formatBytes } from '$lib/format';
  import { jobStore } from '$lib/jobs.svelte';
  import { enlaceAlDocumento } from '$lib/navegacion.svelte';
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
    /** Si es una caja de correspondencia: su inventario es el Índice Electrónico. */
    indice?: boolean;
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
  class="panel panel-sm documento"
  class:panel-bad={entry.failed}
  class:openable={entry.live && mode === 'idle'}
  class:picking={!!onselect}
  class:open={abierta}
>
  <span class="tab" aria-hidden="true"></span>

  {#if mode === 'renaming'}
    <div class="editor">
      <label>
        <span class="caps">Nombre del documento</span>
        <!-- svelte-ignore a11y_autofocus -->
        <input
          class="input input-sm"
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
        conservan el suyo, que sale del número o código de cada uno.
      </p>
      <div class="actions">
        <button class="btn btn-primary btn-sm" onclick={save} disabled={busy || !draft.trim()}>
          {busy ? 'Guardando…' : 'Guardar'}
        </button>
        <button class="btn btn-ghost btn-sm" onclick={() => (mode = 'idle')} disabled={busy}>
          Cancelar
        </button>
      </div>
      {#if failure}<p class="inline-error failure">{failure}</p>{/if}
    </div>
  {:else if mode === 'confirming'}
    <div class="editor">
      <p class="warn">
        Se eliminarán <b>{entry.resolutions}</b>
        {unidad.toLowerCase()} de
        <b>{entry.name}</b>: los PDF generados y sus filas del inventario. No se puede
        deshacer.
      </p>
      <div class="actions">
        <button class="btn btn-danger btn-sm" onclick={remove} disabled={busy}>
          {busy ? 'Eliminando…' : 'Sí, eliminar'}
        </button>
        <button class="btn btn-ghost btn-sm" onclick={() => (mode = 'idle')} disabled={busy}>
          Cancelar
        </button>
      </div>
      {#if failure}<p class="inline-error failure">{failure}</p>{/if}
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
          <span class="sr-only">Seleccionar {entry.name}</span>
        </label>
      {/if}
      <!--
        Lleva al detalle esté en pantalla o archivado. Antes sólo era un enlace
        mientras el trabajo seguía en memoria, así que en cuanto se limpiaba el
        área de trabajo la ficha dejaba de poder abrirse: la tarjeta se veía
        pinchable y no llevaba a ninguna parte.
      -->
      <a class="body" href={enlaceAlDocumento(entry.jobId, 'archivo')}>
        <header>
          <span class="name" title={entry.name}>{entry.name}</span>
          <time class="tabular">{clock}</time>
        </header>

        {#if entry.failed}
          <p class="reason" title={entry.error ?? ''}>{entry.error ?? 'No se pudo procesar'}</p>
        {:else}
          <!-- Two numbers, always in the same place, always meaning the same thing. -->
          <dl class="figures">
            <div class="stat">
              <dt class="stat-label">{unidad}</dt>
              <dd class="stat-value">{entry.resolutions}</dd>
            </div>
            <div class="stat">
              <dt class="stat-label">Páginas</dt>
              <dd class="stat-value">{entry.pages || '—'}</dd>
            </div>
            <div class="stat">
              <dt class="stat-label">Tamaño</dt>
              <dd class="stat-value">{entry.bytes ? formatBytes(entry.bytes) : '—'}</dd>
            </div>
          </dl>
        {/if}
      </a>

        {#if !entry.failed}
          <!-- Fuera del enlace: dentro, pulsarlo abriría el detalle. -->
          <button
            class="btn btn-ghost btn-sm toggle"
            aria-expanded={abierta}
            aria-controls={`archivos-${entry.jobId}`}
            onclick={() => (abierta = !abierta)}
          >
            <Icono nombre="chevron" />
            {#if abierta}
              Ocultar archivos
            {:else}
              {entry.acta ? 'Inventario y PDF divididos' : 'Archivos generados'}
            {/if}
          </button>
        {/if}

      <footer>
        {#if entry.operator}
          <span class="pill by">{entry.operator}</span>
        {:else}
          <span class="by anon">Sin operador</span>
        {/if}

        {#if entry.review}
          <span class="pill pill-warn review tabular" title={`${entry.review} páginas requieren revisión`}>
            <Icono nombre="aviso" />
            {entry.review}
          </span>
        {/if}

        <span class="tools">
          <button
            class="btn btn-ghost btn-sm"
            onclick={startRename}
            title="Cambiar el nombre del documento"
          >
            Renombrar
          </button>
          <button
            class="btn btn-ghost btn-sm quiet"
            onclick={() => {
              failure = null;
              mode = 'confirming';
            }}
            title="Eliminar el documento, sus PDF y su inventario"
          >
            Eliminar
          </button>
          <!--
            Un solo enlace, esté el documento en pantalla o archivado: desde que
            la ficha se dibuja también desde el inventario, los dos abren. Poner
            además el rótulo "archivado" metía un elemento de más en un pie que no
            reparte, y la fila se salía de la tarjeta.
          -->
          <a
            class="btn btn-ghost btn-sm open"
            href={enlaceAlDocumento(entry.jobId, 'archivo')}
            title={entry.live ? undefined : 'Archivado: se dibuja desde el inventario'}
          >
            Ver detalle
            <Icono nombre="chevron" />
          </a>
        </span>
      </footer>

        {#if failure}<p class="inline-error failure">{failure}</p>{/if}
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
  .documento.picking header {
    padding-left: 1.55rem;
  }

  /* Drawn as a folder: a finished document is something you open, not a row you
     scroll past. Es la tarjeta común (`.panel`); sólo la esquina de 4px es
     propia, la que casa con la pestaña de arriba. Al pasar por encima cambia el
     borde y la sombra, sin moverse: nada se mueve por adornar. */
  .documento {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    border-radius: var(--radius-xs) var(--radius-lg) var(--radius-lg) var(--radius-lg);
    transition:
      border-color var(--duration-fast) var(--ease-out),
      box-shadow var(--duration-fast) var(--ease-out);
  }
  .documento.openable:hover {
    border-color: var(--accent);
    box-shadow: var(--shadow-hover);
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
    border-radius: var(--radius-xs) var(--radius-sm) 0 0;
    background: var(--surface-2);
  }
  /* La pestaña sigue al borde de la tarjeta cuando falló (`.panel-bad`). */
  .documento.panel-bad .tab {
    border-color: color-mix(in srgb, var(--critical) 40%, var(--hairline));
  }

  header {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
  }
  .name {
    overflow: hidden;
    flex: 1;
    font-size: var(--text-md);
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  time {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--muted);
  }

  /* Las cifras comunes (`.stat`), las mismas que la tarjeta de una carpeta: una
     carpeta y un PDF suelto se comparan de un vistazo. */
  .figures {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3) var(--space-5);
    margin: 0;
  }

  /* Por qué falló, en un renglón: el texto entero va en el `title`. */
  .reason {
    margin: 0;
    overflow: hidden;
    font-size: var(--text-xs);
    color: var(--critical);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* El hueco lo pone el `gap` de la tarjeta. */
  .failure {
    margin: 0;
  }

  /* Abierta ocupa la fila entera: la lista de PDF de un libro no cabe en una
     columna de la rejilla. */
  .documento.open {
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

  /* Plegar y desplegar es un `.btn-ghost`: no es una acción sobre el
     documento, así que va callado. La flecha gira para decir si está abierto. */
  .toggle {
    align-self: flex-start;
    gap: var(--space-1);
    margin-left: calc(var(--space-2) * -1);
  }
  .toggle :global(.icono) {
    transition: transform var(--duration-fast) var(--ease-out);
  }
  .toggle[aria-expanded='true'] :global(.icono) {
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
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .by.anon {
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .review {
    flex-shrink: 0;
    --icono: 0.75rem;
  }

  /* Tres botones pequeños en una tarjeta de 16.5rem: con el relleno lateral de
     siempre no caben y el pie se salía por el borde, así que aquí se estrecha
     y, si aun así no caben, reparten en dos renglones. */
  .tools {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: 0.15rem;
    margin-left: auto;
  }
  .tools .btn {
    padding-inline: 0.4rem;
  }
  /* Eliminar desde el pie sólo abre la confirmación: va callado, como sus
     vecinos, y avisa en rojo al pasar por encima. El botón de peligro queda
     para el «Sí, eliminar». */
  .tools .quiet:hover:not(:disabled) {
    background: var(--critical-soft);
    color: var(--critical);
  }

  .open,
  .documento.openable:hover .open {
    color: var(--accent);
  }

  /* The editor and the confirmation take the whole card: one thing at a time.
     No se llama `.panel`: esa es la superficie global de una sección. */
  .editor {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .editor label {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }
  .note {
    margin: 0;
    font-size: var(--text-xs);
    line-height: 1.45;
    color: var(--muted);
  }
  .warn {
    margin: 0;
    font-size: var(--text-sm);
    line-height: 1.45;
    color: var(--ink-2);
  }
  .warn b {
    color: var(--ink);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }
</style>
