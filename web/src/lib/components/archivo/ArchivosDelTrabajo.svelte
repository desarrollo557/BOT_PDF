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
  import { formatBytes } from '$lib/format';

  interface Props {
    jobId: string;
  }

  let { jobId }: Props = $props();

  let datos = $state<ArchivosDelTrabajo | null>(null);
  let cargando = $state(true);
  let fallo = $state<string | null>(null);
  let bajando = $state(false);

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

  async function bajarExcel(nombre: string) {
    bajando = true;
    fallo = null;
    try {
      await descargarPlanilla(documentInventoryUrl(jobId), nombre);
    } catch (problema) {
      fallo = (problema as Error).message;
    } finally {
      bajando = false;
    }
  }
</script>

<div class="archivos" aria-live="polite" aria-busy={cargando}>
  {#if cargando}
    <div class="esqueleto" aria-hidden="true">
      {#each [0, 1, 2, 3] as fila (fila)}<span></span>{/each}
    </div>
    <p class="sr">Buscando los archivos…</p>
  {:else if fallo && !datos}
    <p class="error" role="alert">{fallo}</p>
  {:else if datos}
    <header>
      <div class="cuenta">
        <strong class="tabular">{filas.length}</strong>
        <span>{filas.length === 1 ? 'PDF generado' : 'PDF generados'}</span>
        {#if peso}<span class="peso-total tabular">· {formatBytes(peso)}</span>{/if}
      </div>
      <div class="acciones">
        {#if datos.inventario}
          <button class="boton" onclick={() => bajarExcel(datos!.inventario!)} disabled={bajando}>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <rect x="2.5" y="2.5" width="11" height="11" rx="1.5" />
              <path d="M2.5 6.5h11M6.5 6.5v7" />
            </svg>
            {bajando ? 'Descargando…' : 'Inventario (Excel)'}
          </button>
        {/if}
        {#if filas.length > 1}
          <a class="boton principal" href={archivosZipUrl(jobId)} download>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M8 2.5v7m0 0 3-3m-3 3-3-3" />
              <path d="M3 11.5v1A1.5 1.5 0 0 0 4.5 14h7a1.5 1.5 0 0 0 1.5-1.5v-1" />
            </svg>
            Descargar todo (ZIP)
          </a>
        {/if}
      </div>
    </header>

    {#if filas.length}
      <div class="tabla">
        <table>
          <caption class="sr">PDF generados por este documento</caption>
          <thead>
            <tr>
              <th scope="col" class="n">N°</th>
              <th scope="col">Documento</th>
              {#if conFecha}<th scope="col">Fecha</th>{/if}
              <th scope="col" class="num">Tamaño</th>
              <th scope="col" class="accion"><span class="sr">Descargar</span></th>
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
                    href={downloadUrl(jobId, archivo.ruta)}
                    download
                    aria-label={`Descargar ${archivo.titulo}`}
                    title="Descargar PDF"
                  >
                    <svg viewBox="0 0 16 16" aria-hidden="true">
                      <path d="M8 2.5v7m0 0 3-3m-3 3-3-3" />
                      <path d="M3 11.5v1A1.5 1.5 0 0 0 4.5 14h7a1.5 1.5 0 0 0 1.5-1.5v-1" />
                    </svg>
                  </a>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <p class="vacio">Este documento no se dividió: sólo dejó el inventario.</p>
    {/if}

    {#if fallo}<p class="error" role="alert">{fallo}</p>{/if}
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
    font-size: 0.8rem;
    color: var(--ink-2);
  }
  .cuenta strong {
    font-size: 1.05rem;
    font-weight: 650;
    color: var(--ink);
  }
  .peso-total {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--muted);
  }
  .acciones {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .boton {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: var(--surface-2);
    padding: 0.4rem 0.8rem;
    font: inherit;
    font-size: 0.76rem;
    font-weight: 600;
    color: var(--ink-2);
    text-decoration: none;
    cursor: pointer;
    transition:
      border-color 0.15s,
      color 0.15s,
      background-color 0.15s;
  }
  .boton:hover:not(:disabled) {
    border-color: var(--accent);
    color: var(--accent);
  }
  .boton.principal {
    border-color: var(--accent);
    background: var(--accent);
    color: var(--surface-2);
  }
  .boton.principal:hover {
    background: color-mix(in oklab, var(--accent) 85%, white);
    color: var(--surface-2);
  }
  .boton:disabled {
    cursor: default;
    opacity: 0.6;
  }
  .boton:focus-visible,
  .accion a:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }

  .tabla {
    max-height: 26rem;
    overflow: auto;
    border: 1px solid var(--rule);
    border-radius: 10px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.8rem;
  }
  thead th {
    position: sticky;
    top: 0;
    z-index: 1;
    border-bottom: 1px solid var(--rule);
    background: var(--plane);
    padding: 0.45rem 0.7rem;
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.055em;
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
    font-size: 0.66rem;
    color: var(--muted);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .fecha {
    white-space: nowrap;
    font-family: var(--font-mono);
    font-size: 0.74rem;
    color: var(--ink-2);
  }
  td.num {
    text-align: right;
    white-space: nowrap;
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--muted);
  }
  th.num {
    text-align: right;
  }
  .accion {
    width: 2.75rem;
    text-align: center;
  }
  .accion a {
    display: inline-grid;
    width: 1.9rem;
    height: 1.9rem;
    place-items: center;
    border-radius: 7px;
    color: var(--accent);
  }
  .accion a:hover {
    background: var(--accent-soft);
  }

  svg {
    width: 0.9rem;
    height: 0.9rem;
    flex-shrink: 0;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.6;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .esqueleto {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .esqueleto span {
    height: 1.9rem;
    border-radius: 7px;
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

  .vacio {
    margin: 0;
    border: 1px dashed var(--hairline);
    border-radius: 10px;
    padding: 1rem;
    font-size: 0.78rem;
    text-align: center;
    color: var(--muted);
  }
  .error {
    margin: 0;
    font-size: 0.74rem;
    color: var(--critical);
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
</style>
