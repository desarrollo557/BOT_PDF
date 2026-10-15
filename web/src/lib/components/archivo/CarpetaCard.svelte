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
  import {
    deleteDocuments,
    descargarPlanilla,
    origenInventarioUrl,
    origenProcesosUrl
  } from '$lib/api';
  import { unidades, type Grupo } from '$lib/archive.svelte';
  import Descargas, { type GrupoDeDescargas } from '$lib/components/Descargas.svelte';
  import Icono from '$lib/components/Icono.svelte';
  import { formatBytes } from '$lib/format';
  import { jobStore } from '$lib/jobs.svelte';
  import { enlaceAlDocumento } from '$lib/navegacion.svelte';
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
  let fallo = $state<string | null>(null);

  /**
   * Lo que se baja de la carpeta o el lote: sus dos inventarios generales. El
   * de la habilidad -- de cajas de correspondencia, el Índice Electrónico del
   * cliente con una hoja por PDF; de actas, una fila por acta -- y el general
   * del bot, una fila por cada PDF procesado.
   */
  const descargas = $derived<GrupoDeDescargas[]>([
    {
      titulo: 'Inventarios generales',
      items: [
        ...(grupo.indice || (grupo.acta && esCarpeta)
          ? [
              {
                id: 'habilidad',
                titulo: grupo.indice ? 'Índice electrónico' : 'Inventario de actas',
                detalle: grupo.indice
                  ? 'Plantilla del cliente, una hoja por PDF procesado'
                  : 'Una fila por acta de toda la carpeta',
                formato: 'Excel' as const,
                principal: true,
                bajar: () =>
                  descargarPlanilla(
                    origenInventarioUrl(grupo.origen.id),
                    grupo.indice
                      ? '00.INDICE ELECTRONICO.xlsx'
                      : `ACTAS ${grupo.origen.nombre}__inventario.xlsx`
                  )
              }
            ]
          : []),
        {
          id: 'procesos',
          titulo: 'Inventario de procesos',
          detalle: 'Lo que hizo el bot con cada PDF: habilidad, lectura, resultado y revisión',
          formato: 'Excel' as const,
          bajar: () =>
            descargarPlanilla(
              origenProcesosUrl(grupo.origen.id),
              '00.INVENTARIO GENERAL DE PROCESOS.xlsx'
            )
        }
      ]
    }
  ]);

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
      <span class="sr-only">Seleccionar la carpeta {grupo.origen.nombre}</span>
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
        <span class="pill pill-warn">{grupo.review} {grupo.review === 1 ? 'página' : 'páginas'} por revisar</span>
      {/if}
      {#if grupo.failed}
        <span class="pill pill-bad">{grupo.failed} {grupo.failed === 1 ? 'PDF falló' : 'PDF fallaron'}</span>
      {/if}
    </p>
  {/if}

  <Descargas grupos={descargas} />

  <button
    class="toggle"
    aria-expanded={abierta}
    onclick={() => (abierta = !abierta)}
  >
    <Icono nombre="chevron" />
    {abierta ? 'Ocultar' : 'Ver'} los {grupo.entries.length} PDF
  </button>

  {#if abierta}
    <ul class="files">
      {#each grupo.entries as entry (entry.key)}
        <li class:failed={entry.failed} class:shown={desplegado === entry.jobId}>
          <div class="file-row">
            <a href={enlaceAlDocumento(entry.jobId, 'archivo', grupo.origen.nombre)} title={entry.name}>
              <span class="file">{entry.name}</span>
              <span class="file-meta tabular">
                {#if entry.failed}
                  Falló
                {:else}
                  {entry.resolutions} PDF · {entry.pages || '—'} pág.
                  {#if entry.review}<b>· {entry.review} rev.</b>{/if}
                {/if}
              </span>
            </a>
            {#if !entry.failed}
              <button
                class="btn btn-sm file-toggle"
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
        Se eliminarán los {grupo.entries.length} PDF de {esCarpeta ? 'esta carpeta' : 'este lote'} del
        archivo, con lo que produjeron. Lo entregado en el destino no se toca.
      </span>
      <span class="tools">
        <button class="btn btn-danger btn-sm" onclick={eliminar} disabled={ocupada}>
          {ocupada ? 'Eliminando…' : 'Sí, eliminar'}
        </button>
        <button class="btn btn-ghost btn-sm" onclick={() => (confirmando = false)} disabled={ocupada}>
          Cancelar
        </button>
      </span>
    {:else}
      <span class="tools">
        <button
          class="btn btn-ghost btn-sm quiet"
          onclick={() => ((fallo = null), (confirmando = true))}
        >
          Eliminar {esCarpeta ? 'carpeta' : 'lote'}
        </button>
      </span>
    {/if}
  </footer>

  {#if fallo}<p class="inline-error error">{fallo}</p>{/if}
</article>

<style>
  /* La misma tarjeta que la de un PDF suelto -- radio, hairline, sombra --: lo
     que la distingue es el ícono de carpeta y su rótulo, no un borde de color. */
  .card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    border: 1px solid var(--hairline);
    border-radius: var(--radius-md);
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
    border-radius: var(--radius);
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
    font-size: var(--text-lg);
    font-weight: 650;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem 0.5rem;
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .kind {
    border-radius: var(--radius-pill);
    background: var(--plane);
    padding: 0 0.45rem;
    font-weight: 600;
    color: var(--ink-2);
  }
  time {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--axis);
  }

  /* Las mismas cifras que la tarjeta de un PDF suelto, con la misma escala. */
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
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
    text-transform: uppercase;
    color: var(--muted);
  }
  .figures dd {
    margin: 0;
    font-family: var(--font-mono);
    font-size: var(--text-lg);
    color: var(--ink);
  }

  .flags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin: 0;
  }

  /* Plegar y desplegar queda como texto: no es una acción sobre la carpeta. */
  .toggle {
    display: inline-flex;
    align-self: flex-start;
    align-items: center;
    gap: 0.25rem;
    border: 0;
    background: none;
    padding: 0;
    font: inherit;
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--ink-2);
    cursor: pointer;
  }
  .toggle:hover {
    color: var(--accent);
  }
  .toggle :global(.icono) {
    transition: transform 0.15s ease;
  }
  .toggle[aria-expanded='true'] :global(.icono) {
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
    min-height: 0;
  }
  /* Desplegado, el botón queda marcado: dice de qué PDF son los archivos de
     debajo. */
  .file-toggle[aria-expanded='true'] {
    border-color: var(--accent);
    color: var(--accent);
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
    border-radius: var(--radius-sm);
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
    font-size: var(--text-xs);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .file-meta {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    color: var(--muted);
  }
  .file-meta b {
    color: var(--warning-ink);
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
    font-size: var(--text-xs);
    line-height: 1.45;
    color: var(--ink-2);
  }
  .tools {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: 0.3rem;
    margin-left: auto;
  }
  /* Eliminar desde el pie sólo abre la confirmación: va callado y avisa en
     rojo al pasar por encima. El botón de peligro queda para el «Sí, eliminar». */
  .tools .quiet:hover:not(:disabled) {
    background: var(--critical-soft);
    color: var(--critical);
  }

  /* El hueco lo pone el `gap` de la tarjeta. */
  .error {
    margin: 0;
  }
</style>
