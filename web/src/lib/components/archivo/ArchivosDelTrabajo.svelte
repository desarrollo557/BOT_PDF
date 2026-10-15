<script lang="ts">
  /**
   * Lo que dejó un trabajo, para bajarlo desde su tarjeta: el inventario en
   * Excel y los PDF en que se dividió.
   *
   * Se pide al abrirse y no antes: una lista de doscientas tarjetas no tiene
   * por qué preguntar doscientas veces qué hay en cada carpeta. Y se lee del
   * disco, no del inventario, porque es lo que de verdad se puede descargar.
   *
   * Los nombres se enseñan como se leen -- «ACTA EXTRAORDINARIA No. 017» y su
   * fecha en su columna -- y el nombre del disco va debajo, pequeño, para quien
   * lo busque en la carpeta.
   */
  import { describirArchivo } from '$lib/actas';
  import {
    archivosZipUrl,
    descargarPlanilla,
    documentInventoryUrl,
    downloadUrl,
    fetchArchivos,
    type ArchivosDelTrabajo
  } from '$lib/api';
  import Descargas, { type GrupoDeDescargas } from '$lib/components/Descargas.svelte';
  import Icono from '$lib/components/Icono.svelte';
  import { formatBytes } from '$lib/format';

  interface Props {
    jobId: string;
  }

  let { jobId }: Props = $props();

  let datos = $state<ArchivosDelTrabajo | null>(null);
  let cargando = $state(true);
  let fallo = $state<string | null>(null);

  $effect(() => {
    const id = jobId;
    cargando = true;
    fallo = null;
    fetchArchivos(id)
      .then((respuesta) => {
        if (id === jobId) datos = respuesta;
      })
      .catch((problema) => {
        if (id === jobId) fallo = (problema as Error).message;
      })
      .finally(() => {
        if (id === jobId) cargando = false;
      });
  });

  const filas = $derived(
    (datos?.archivos ?? []).map((archivo) => ({ ...archivo, ...describirArchivo(archivo.nombre) }))
  );
  const peso = $derived(filas.reduce((total, archivo) => total + archivo.bytes, 0));
  const conFecha = $derived(filas.some((archivo) => archivo.fecha));

  /**
   * Lo que se baja de este PDF: el inventario de su habilidad -- el Índice
   * Electrónico de una caja de correspondencia, la planilla de las demás -- y
   * sus PDF juntos.
   */
  const descargas = $derived<GrupoDeDescargas[]>([
    {
      titulo: 'Inventario',
      items: datos?.inventario
        ? [
            {
              id: 'inventario',
              titulo: datos.inventario.startsWith('00.INDICE')
                ? 'Índice electrónico'
                : 'Inventario del documento',
              detalle: datos.inventario.startsWith('00.INDICE')
                ? 'Plantilla del cliente, una fila por documento'
                : 'Una fila por PDF generado',
              formato: 'Excel' as const,
              principal: true,
              bajar: () => descargarPlanilla(documentInventoryUrl(jobId), datos!.inventario!)
            }
          ]
        : []
    },
    {
      titulo: 'Archivos',
      items:
        filas.length > 1
          ? [
              {
                id: 'zip',
                titulo: 'Todos los PDF',
                detalle: `${filas.length} archivos${peso ? `, ${formatBytes(peso)}` : ''}`,
                formato: 'ZIP' as const,
                href: archivosZipUrl(jobId)
              }
            ]
          : []
    }
  ]);
</script>

<div class="archivos" aria-live="polite" aria-busy={cargando}>
  {#if cargando}
    <div class="esqueleto" aria-hidden="true">
      {#each [0, 1, 2, 3] as fila (fila)}<span></span>{/each}
    </div>
    <p class="sr-only">Buscando los archivos…</p>
  {:else if fallo && !datos}
    <p class="inline-error error" role="alert">{fallo}</p>
  {:else if datos}
    <header>
      <div class="cuenta">
        <strong class="tabular">{filas.length}</strong>
        <span>{filas.length === 1 ? 'PDF generado' : 'PDF generados'}</span>
        {#if peso}<span class="peso-total tabular">· {formatBytes(peso)}</span>{/if}
      </div>
    </header>
    <div class="descargas">
      <Descargas grupos={descargas} />
    </div>

    {#if filas.length}
      <div class="tabla">
        <table>
          <caption class="sr-only">PDF generados por este documento</caption>
          <thead>
            <tr>
              <th scope="col" class="n">N°</th>
              <th scope="col">Documento</th>
              {#if conFecha}<th scope="col">Fecha</th>{/if}
              <th scope="col" class="num">Tamaño</th>
              <th scope="col" class="accion"><span class="sr-only">Descargar</span></th>
            </tr>
          </thead>
          <tbody>
            {#each filas as archivo (archivo.ruta)}
              <tr>
                <td class="n tabular">{archivo.orden ?? '—'}</td>
                <td class="doc">
                  <span class="titulo">{archivo.titulo}</span>
                  <span class="disco" title={archivo.ruta}>{archivo.nombre}</span>
                </td>
                {#if conFecha}<td class="tabular fecha">{archivo.fecha ?? '—'}</td>{/if}
                <td class="num tabular">{formatBytes(archivo.bytes)}</td>
                <td class="accion">
                  <a
                    class="btn btn-icon"
                    href={downloadUrl(jobId, archivo.ruta)}
                    download
                    aria-label={`Descargar ${archivo.titulo}`}
                    title="Descargar PDF"
                  >
                    <Icono nombre="descargar" />
                  </a>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <p class="empty-state vacio">Este documento no se dividió: sólo dejó el inventario.</p>
    {/if}

    {#if fallo}<p class="inline-error error" role="alert">{fallo}</p>{/if}
  {/if}
</div>

<style>
  .archivos {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 0.75rem;
  }

  header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem 1rem;
  }
  .cuenta {
    display: flex;
    align-items: baseline;
    gap: 0.35rem;
    font-size: var(--text-sm);
    color: var(--ink-2);
  }
  .cuenta strong {
    font-size: var(--text-lg);
    font-weight: 650;
    color: var(--ink);
  }
  .peso-total {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .descargas {
    margin-bottom: 0.75rem;
    max-width: 34rem;
  }

  .tabla {
    max-height: 26rem;
    overflow: auto;
    border: 1px solid var(--rule);
    border-radius: var(--radius-md);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  thead th {
    position: sticky;
    top: 0;
    z-index: 1;
    border-bottom: 1px solid var(--rule);
    background: var(--plane);
    padding: 0.45rem 0.7rem;
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
    text-align: left;
    text-transform: uppercase;
    color: var(--muted);
  }
  tbody tr + tr {
    border-top: 1px solid var(--rule);
  }
  tbody tr:hover {
    background: color-mix(in oklab, var(--accent) 6%, transparent);
  }
  td {
    padding: 0.45rem 0.7rem;
    vertical-align: middle;
  }
  .n {
    width: 2.5rem;
    font-family: var(--font-mono);
    color: var(--muted);
  }
  .doc {
    min-width: 0;
  }
  .titulo {
    display: block;
    font-weight: 600;
    color: var(--ink);
  }
  .disco {
    display: block;
    overflow: hidden;
    max-width: 32rem;
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    color: var(--muted);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .fecha {
    white-space: nowrap;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--ink-2);
  }
  td.num {
    text-align: right;
    white-space: nowrap;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--muted);
  }
  th.num {
    text-align: right;
  }
  .accion {
    width: 2.75rem;
    text-align: center;
  }

  .esqueleto {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .esqueleto span {
    height: 1.9rem;
    border-radius: var(--radius-sm);
    background: var(--plane);
    animation: pulso 1.2s ease-in-out infinite;
  }
  @keyframes pulso {
    50% {
      opacity: 0.5;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .esqueleto span {
      animation: none;
    }
  }

  /* La caja punteada global, a escala de una tarjeta. */
  .vacio {
    margin: 0;
    padding: 1rem;
    font-size: var(--text-sm);
  }
  /* El hueco lo pone el `gap` de la columna. */
  .error {
    margin: 0;
  }
</style>
