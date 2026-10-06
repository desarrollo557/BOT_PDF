<script lang="ts">
  /**
   * Una carpeta local, o un lote, procesado entero: una sola tarjeta.
   *
   * Cada PDF de una corrida por carpeta es un trabajo propio, y el Archivo los
   * dibujaba sueltos, cada uno como una «carpeta» con el nombre de su archivo.
   * El operador buscaba «UPD3859771» y encontraba «1N°22-17 DE DICIEMBRE DE
   * 2012.pdf». Aquí la carpeta lleva el nombre de la carpeta raíz, sus cifras
   * sumadas, su inventario general y sus PDF dentro, plegados.
   */
  import { deleteDocuments, descargarPlanilla, origenInventarioUrl } from '$lib/api';
  import { unidades, type Grupo } from '$lib/archive.svelte';
  import { formatBytes } from '$lib/format';
  import { jobStore } from '$lib/jobs.svelte';
  import ArchivosDelTrabajo from './ArchivosDelTrabajo.svelte';

  interface Props {
    grupo: Grupo;
    /** Lo marcado en la lista, para pintar la casilla de la carpeta. */
    selected?: Set<string>;
    /** Marcar o desmarcar todos sus PDF de una vez. Sin esto no hay casilla. */
    onselectmany?: (jobIds: string[]) => void;
    /** Tras borrar la carpeta, para que la página recargue. */
    onchange?: () => void;
  }

  let { grupo, selected, onselectmany, onchange }: Props = $props();

  const ids = $derived(grupo.entries.map((entry) => entry.jobId));
  const marcados = $derived(ids.filter((id) => selected?.has(id)).length);
  const unidad = $derived(unidades(grupo.tipos, grupo.acta));
  const esCarpeta = $derived(grupo.origen.tipo !== 'lote');
  const clock = $derived(
    new Date(grupo.at).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })
  );

  let abierta = $state(false);
  /** De qué PDF de la carpeta se están enseñando sus archivos. */
  let desplegado = $state<string | null>(null);
  let confirmando = $state(false);
  let ocupada = $state(false);
  let bajando = $state(false);
  let fallo = $state<string | null>(null);

  /** El Excel general: una fila por acta de todos los PDF de la carpeta. */
  async function bajarInventario() {
    bajando = true;
    fallo = null;
    try {
      await descargarPlanilla(
        origenInventarioUrl(grupo.origen.id),
        `ACTAS ${grupo.origen.nombre}__inventario.xlsx`
      );
    } catch (problema) {
      fallo = (problema as Error).message;
    } finally {
      bajando = false;
    }
  }

  async function eliminar() {
    ocupada = true;
    fallo = null;
    try {
      const resultado = await deleteDocuments(ids);
      for (const item of resultado.deleted) jobStore.forget(item.job_id);
      if (resultado.failed.length) {
        fallo = `No se pudieron eliminar ${resultado.failed.length} de sus PDF.`;
      }
      confirmando = false;
      onchange?.();
    } catch (problema) {
      fallo = (problema as Error).message;
    } finally {
      ocupada = false;
    }
  }
</script>

<article class="card" class:open={abierta} class:picking={!!onselectmany}>
  {#if onselectmany}
    <label class="pick" title="Seleccionar todos sus PDF">
      <input
        type="checkbox"
        checked={marcados > 0 && marcados === ids.length}
        indeterminate={marcados > 0 && marcados < ids.length}
        onclick={() => onselectmany(ids)}
      />
      <span class="sr">Seleccionar la carpeta {grupo.origen.nombre}</span>
    </label>
  {/if}

  <header>
    <span class="icon" aria-hidden="true">
      {#if esCarpeta}
        <svg viewBox="0 0 20 20">
          <path d="M2.5 5.5A1.5 1.5 0 0 1 4 4h3.6l1.6 1.8H16a1.5 1.5 0 0 1 1.5 1.5v7.2A1.5 1.5 0 0 1 16 16H4a1.5 1.5 0 0 1-1.5-1.5v-9Z" />
        </svg>
      {:else}
        <svg viewBox="0 0 20 20">
          <rect x="4.5" y="3" width="11" height="14" rx="1.5" />
          <path d="M2.5 6v9.5A1.5 1.5 0 0 0 4 17M7.5 7h5M7.5 10h5M7.5 13h3" />
        </svg>
      {/if}
    </span>
    <div class="title">
      <span class="name" title={grupo.origen.nombre}>{grupo.origen.nombre}</span>
      <span class="meta">
        <span class="kind">{esCarpeta ? 'Carpeta local' : 'Lote'}</span>
        <span>{grupo.entries.length} PDF</span>
        {#if grupo.operators.length}<span>{grupo.operators.join(', ')}</span>{/if}
      </span>
    </div>
    <time class="tabular">{clock}</time>
  </header>

  <dl class="figures">
    <div>
      <dt>{unidad}</dt>
      <dd class="tabular">{grupo.resolutions}</dd>
    </div>
    <div>
      <dt>Páginas</dt>
      <dd class="tabular">{grupo.pages || '—'}</dd>
    </div>
    <div>
      <dt>Tamaño</dt>
      <dd class="tabular">{grupo.bytes ? formatBytes(grupo.bytes) : '—'}</dd>
    </div>
  </dl>

  {#if grupo.review || grupo.failed}
    <p class="flags">
      {#if grupo.review}
        <span class="flag warn">{grupo.review} {grupo.review === 1 ? 'página' : 'páginas'} por revisar</span>
      {/if}
      {#if grupo.failed}
        <span class="flag bad">{grupo.failed} {grupo.failed === 1 ? 'PDF falló' : 'PDF fallaron'}</span>
      {/if}
    </p>
  {/if}

  {#if grupo.acta && esCarpeta}
    <button class="bajar" onclick={bajarInventario} disabled={bajando}>
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M8 2.5v7m0 0 3-3m-3 3-3-3" />
        <path d="M3 11.5v1A1.5 1.5 0 0 0 4.5 14h7a1.5 1.5 0 0 0 1.5-1.5v-1" />
      </svg>
      {bajando ? 'Descargando…' : 'Descargar inventario general (Excel)'}
    </button>
  {/if}

  <button
    class="toggle"
    aria-expanded={abierta}
    onclick={() => (abierta = !abierta)}
  >
    <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3.5 4.5 4.5L6 12.5" /></svg>
    {abierta ? 'Ocultar' : 'Ver'} los {grupo.entries.length} PDF
  </button>

  {#if abierta}
    <ul class="files">
      {#each grupo.entries as entry (entry.key)}
        <li class:failed={entry.failed} class:shown={desplegado === entry.jobId}>
          <div class="file-row">
            <a href={`/documento/${entry.jobId}`} title={entry.name}>
              <span class="file">{entry.name}</span>
              <span class="file-meta tabular">
                {#if entry.failed}
                  falló
                {:else}
                  {entry.resolutions} · {entry.pages || '—'} pág
                  {#if entry.review}<b>· {entry.review} rev.</b>{/if}
                {/if}
              </span>
            </a>
            {#if !entry.failed}
              <button
                class="file-toggle"
                aria-expanded={desplegado === entry.jobId}
                aria-label={`Inventario y PDF de ${entry.name}`}
                onclick={() => (desplegado = desplegado === entry.jobId ? null : entry.jobId)}
              >
                {entry.acta ? 'Inventario y PDF' : 'Archivos'}
              </button>
            {/if}
          </div>
          {#if desplegado === entry.jobId}
            <div class="file-panel">
              <ArchivosDelTrabajo jobId={entry.jobId} />
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}

  <footer>
    {#if confirmando}
      <span class="confirm">
        Se eliminarán los {grupo.entries.length} PDF de esta {esCarpeta ? 'carpeta' : 'lote'} del
        archivo, con lo que produjeron. Lo entregado en el destino no se toca.
      </span>
      <span class="tools">
        <button class="danger" onclick={eliminar} disabled={ocupada}>
          {ocupada ? 'eliminando…' : 'sí, eliminar'}
        </button>
        <button onclick={() => (confirmando = false)} disabled={ocupada}>cancelar</button>
      </span>
    {:else}
      <span class="tools">
        <button class="quiet" onclick={() => ((fallo = null), (confirmando = true))}>
          eliminar {esCarpeta ? 'carpeta' : 'lote'}
        </button>
      </span>
    {/if}
  </footer>

  {#if fallo}<p class="error">{fallo}</p>{/if}
</article>

<style>
  .card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    border: 1px solid var(--hairline);
    border-left: 3px solid var(--accent);
    border-radius: 10px;
    background: var(--surface-2);
    padding: 0.8rem 0.9rem;
    box-shadow: var(--shadow);
  }

  /* Abierta ocupa el ancho de la fila: una lista de cuarenta PDF no cabe en
     una columna de la rejilla sin volverse ilegible. */
  .card.open {
    grid-column: 1 / -1;
  }

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
  .card.picking header {
    padding-left: 1.55rem;
  }

  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }

  header {
    display: flex;
    align-items: flex-start;
    gap: 0.6rem;
  }
  .icon {
    display: grid;
    width: 2rem;
    height: 2rem;
    flex-shrink: 0;
    place-items: center;
    border-radius: 8px;
    background: var(--accent-soft);
    color: var(--accent);
  }
  .icon svg {
    width: 1.1rem;
    height: 1.1rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linejoin: round;
    stroke-linecap: round;
  }
  .title {
    display: flex;
    min-width: 0;
    flex: 1;
    flex-direction: column;
    gap: 0.15rem;
  }
  .name {
    overflow: hidden;
    font-size: 0.92rem;
    font-weight: 650;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem 0.5rem;
    font-size: 0.7rem;
    color: var(--muted);
  }
  .kind {
    border-radius: 999px;
    background: var(--plane);
    padding: 0 0.45rem;
    font-weight: 600;
    color: var(--ink-2);
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

  .flags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin: 0;
  }
  .flag {
    border-radius: 999px;
    padding: 0 0.45rem;
    font-size: 0.68rem;
    font-weight: 600;
  }
  .flag.warn {
    background: color-mix(in oklab, var(--warning) 16%, transparent);
    color: var(--warning);
  }
  .flag.bad {
    background: color-mix(in oklab, var(--critical) 14%, transparent);
    color: var(--critical);
  }

  .bajar {
    display: flex;
    width: 100%;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    border: 1px solid color-mix(in oklab, var(--accent) 55%, var(--hairline));
    border-radius: 8px;
    background: color-mix(in oklab, var(--accent) 8%, transparent);
    padding: 0.45rem 0.6rem;
    font: inherit;
    font-size: 0.76rem;
    font-weight: 600;
    color: var(--accent);
    cursor: pointer;
  }
  .card.open .bajar {
    align-self: flex-start;
    width: auto;
    padding-inline: 1rem;
  }
  .bajar:hover:not(:disabled) {
    background: color-mix(in oklab, var(--accent) 16%, transparent);
  }
  .bajar:disabled {
    cursor: default;
    opacity: 0.6;
  }

  .bajar svg,
  .toggle svg {
    width: 0.9rem;
    height: 0.9rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.6;
    stroke-linecap: round;
    stroke-linejoin: round;
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
    color: var(--ink-2);
    cursor: pointer;
  }
  .toggle:hover {
    color: var(--accent);
  }
  .toggle svg {
    transition: transform 0.15s ease;
  }
  .toggle[aria-expanded='true'] svg {
    transform: rotate(90deg);
  }

  .files {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 18rem), 1fr));
    gap: 4px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .files li.shown {
    grid-column: 1 / -1;
  }
  .file-row {
    display: flex;
    align-items: stretch;
    gap: 4px;
  }
  .file-row a {
    flex: 1;
    min-width: 0;
  }
  .file-toggle {
    flex-shrink: 0;
    border: 1px solid var(--rule);
    border-radius: 7px;
    background: none;
    padding: 0 0.55rem;
    font: inherit;
    font-size: 0.68rem;
    font-weight: 600;
    color: var(--accent);
    cursor: pointer;
  }
  .file-toggle:hover,
  .file-toggle[aria-expanded='true'] {
    border-color: var(--accent);
  }
  .file-panel {
    margin: 4px 0 6px;
    border-left: 2px solid var(--accent);
    padding: 0.4rem 0 0.2rem 0.7rem;
  }
  .files a {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.6rem;
    border: 1px solid var(--rule);
    border-radius: 7px;
    padding: 0.35rem 0.55rem;
    color: inherit;
    text-decoration: none;
  }
  .files a:hover {
    border-color: var(--accent);
  }
  .file {
    overflow: hidden;
    min-width: 0;
    font-size: 0.76rem;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .file-meta {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 0.66rem;
    color: var(--muted);
  }
  .file-meta b {
    color: var(--warning);
  }
  .files li.failed .file-meta {
    color: var(--critical);
  }

  footer {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.45rem;
    border-top: 1px solid var(--rule);
    padding-top: 0.5rem;
  }
  .confirm {
    flex: 1 1 14rem;
    font-size: 0.74rem;
    line-height: 1.45;
    color: var(--ink-2);
  }
  .tools {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-left: auto;
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
  .tools button.quiet:hover,
  .tools button.danger {
    color: var(--critical);
  }
  .tools button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .error {
    margin: 0;
    font-size: 0.72rem;
    color: var(--critical);
  }
</style>
